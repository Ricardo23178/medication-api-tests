"""用药计划的生命周期：创建 → 暂停 → 恢复 → 改版 → 删除。

计划是整个系统的中枢：提醒任务由它生成，统计由它算分母，
家属看板也挂在它上面。所以它的状态机（ACTIVE / PAUSED）必须严格。
"""

import pytest

from api.client import expect_error, ok
from api.support import future_remind_time, future_remind_times, today


def _plan_payload(medicine_id, **overrides):
    payload = {
        "medicineId": medicine_id,
        "dosagePerTime": 1,
        "dosageUnit": "片",
        "startDate": today().isoformat(),
        "mealRelation": 1,
        "remark": "早餐后",
        "remindTimes": future_remind_times(2),
    }
    payload.update(overrides)
    return payload


def test_create_plan_is_active(user, medicine):
    data = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))

    assert data["status"] == "ACTIVE"
    assert data["medicineId"] == medicine["id"]
    assert data["medicineName"] == medicine["name"], "列表要能直接显示药名，不让前端再查一次"
    assert data["planVersion"] == 1
    assert len(data["times"]) == 2


def test_create_plan_keeps_all_remind_times(user, medicine):
    times = future_remind_times(3, start_minutes=30, step=15)

    data = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"], remindTimes=times)))

    stored = sorted(item["remindTime"][:5] for item in data["times"])
    assert stored == sorted(times)


@pytest.mark.parametrize("remind_times", [None, []])
def test_create_plan_requires_at_least_one_remind_time(user, medicine, remind_times):
    payload = _plan_payload(medicine["id"])
    if remind_times is None:
        payload.pop("remindTimes")
    else:
        payload["remindTimes"] = remind_times

    expect_error(user.client.post("/api/plans", json=payload), 400, "提醒时间点必须为1至24个")


def test_create_plan_rejects_more_than_24_times(user, medicine):
    too_many = ["08:00"] * 25

    expect_error(
        user.client.post("/api/plans", json=_plan_payload(medicine["id"], remindTimes=too_many)),
        400,
        "提醒时间点必须为1至24个",
    )


def test_create_plan_rejects_duplicate_times(user, medicine):
    """同一时间点重复两次等于给患者连发两条提醒，必须拦掉。"""
    expect_error(
        user.client.post(
            "/api/plans", json=_plan_payload(medicine["id"], remindTimes=["08:00", "08:00"])
        ),
        400,
        "提醒时间点不能重复",
    )


def test_create_plan_rejects_end_date_before_start(user, medicine):
    expect_error(
        user.client.post(
            "/api/plans",
            json=_plan_payload(
                medicine["id"], startDate="2026-10-28", endDate="2026-01-01"
            ),
        ),
        400,
        "结束日期不能早于开始日期",
    )


def test_create_plan_rejects_nonexistent_medicine(user):
    expect_error(
        user.client.post("/api/plans", json=_plan_payload(99999999)), 400, "药品不存在或无权使用"
    )


def test_create_plan_rejects_other_users_medicine(user, other_user):
    """用别人的药品建计划必须被拒 —— 否则等于绕过药品的权限隔离。"""
    foreign = ok(other_user.client.post("/api/medicines", json={"name": "别人的药"}))

    expect_error(
        user.client.post("/api/plans", json=_plan_payload(foreign["id"])),
        400,
        "药品不存在或无权使用",
    )


def test_create_plan_requires_medicine_id(user):
    payload = _plan_payload(1)
    payload.pop("medicineId")

    expect_error(user.client.post("/api/plans", json=payload), 400, "必须指定药品")


def test_pause_then_resume(user, medicine):
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))

    paused = ok(user.client.post(f"/api/plans/{plan['id']}/pause"))
    assert paused["status"] == "PAUSED"

    resumed = ok(user.client.post(f"/api/plans/{plan['id']}/resume"))
    assert resumed["status"] == "ACTIVE"


def test_pause_is_not_repeatable(user, medicine):
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))
    ok(user.client.post(f"/api/plans/{plan['id']}/pause"))

    expect_error(
        user.client.post(f"/api/plans/{plan['id']}/pause"), 400, "当前状态不可暂停"
    )


def test_resume_is_not_repeatable(user, medicine):
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))

    expect_error(user.client.post(f"/api/plans/{plan['id']}/resume"), 400, "当前状态不可恢复")


def test_pausing_bumps_plan_version(user, medicine):
    """版本号是提醒任务快照的依据：改了计划，旧任务不能继续按旧规则生效。"""
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))
    before = plan["planVersion"]

    paused = ok(user.client.post(f"/api/plans/{plan['id']}/pause"))

    assert paused["planVersion"] > before


def test_update_plan_replaces_remind_times(user, medicine):
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))
    new_time = future_remind_time(45)

    updated = ok(
        user.client.put(
            f"/api/plans/{plan['id']}",
            json=_plan_payload(medicine["id"], remindTimes=[new_time], remark="改成一天一次"),
        )
    )

    assert [item["remindTime"][:5] for item in updated["times"]] == [new_time], (
        "改计划应替换时间点，而不是叠加"
    )
    assert updated["remark"] == "改成一天一次"
    assert updated["planVersion"] > plan["planVersion"]


def test_delete_plan_removes_it_from_list(user, medicine):
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))

    ok(user.client.delete(f"/api/plans/{plan['id']}"))

    remaining = [item["id"] for item in ok(user.client.get("/api/plans"))]
    assert plan["id"] not in remaining
    expect_error(user.client.get(f"/api/plans/{plan['id']}"), 403, "计划不存在或无权查看")


def test_other_user_cannot_operate_plan(user, other_user, medicine):
    """越权读、改、删、暂停，四条路都要堵住。"""
    plan = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))
    payload = _plan_payload(medicine["id"])

    expect_error(other_user.client.get(f"/api/plans/{plan['id']}"), 403, "计划不存在或无权查看")
    expect_error(
        other_user.client.put(f"/api/plans/{plan['id']}", json=payload), 403, "计划不存在或无权修改"
    )
    expect_error(
        other_user.client.post(f"/api/plans/{plan['id']}/pause"), 400, "计划不存在或当前状态不可暂停"
    )
    expect_error(
        other_user.client.delete(f"/api/plans/{plan['id']}"), 403, "计划不存在或无权删除"
    )


def test_plan_list_only_returns_own_plans(user, other_user, medicine):
    mine = ok(user.client.post("/api/plans", json=_plan_payload(medicine["id"])))

    theirs = ok(other_user.client.get("/api/plans"))

    assert mine["id"] not in [item["id"] for item in theirs]
