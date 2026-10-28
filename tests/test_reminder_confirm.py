"""提醒任务与确认服药 —— 整个系统最核心的一条链路。

链路是：ACTIVE 计划 → 今天的时间点 → 生成任务实例 → 患者确认 → 写服药记录 → 统计变化。

几个容易忽略但必须锁住的点：
1. 任务在「查今日清单」时按需生成，不依赖定时器（否则测试只能等 5 分钟）。
2. 确认是幂等的：重复点击不能产生第二条记录，也不能报错。
3. 任务有确认窗口，超时后不允许再确认（本文件用参数校验覆盖窗口边界，超时场景见 README 的未覆盖说明）。
"""

import pytest

from api.client import expect_error, ok
from api.support import future_remind_time, future_remind_times, today


def _create_plan(user, medicine_id, times=None, **overrides):
    payload = {
        "medicineId": medicine_id,
        "dosagePerTime": 1,
        "dosageUnit": "片",
        "startDate": today().isoformat(),
        "remindTimes": times or future_remind_times(2),
    }
    payload.update(overrides)
    return ok(user.client.post("/api/plans", json=payload))


def _today_tasks(user):
    return ok(user.client.get("/api/reminders/today"))


@pytest.fixture
def plan_with_tasks(user, medicine):
    """一个 ACTIVE 计划 + 它今天的任务实例。"""
    plan = _create_plan(user, medicine["id"])
    tasks = _today_tasks(user)
    assert tasks, "计划创建后查今日清单应生成任务"
    return plan, tasks


def test_today_returns_empty_for_new_user(user):
    """新账号没有任何计划，今日清单应为空数组而不是报错。"""
    assert _today_tasks(user) == []


def test_today_generates_tasks_from_active_plan(user, medicine, plan_with_tasks):
    plan, tasks = plan_with_tasks

    assert len(tasks) == 2, "两个提醒时间点应生成两条任务"
    for task in tasks:
        assert task["planId"] == plan["id"]
        assert task["medicineName"] == medicine["name"], "任务要带药名快照，药品改名后历史任务仍可读"
        assert task["status"] == "WAITING"
        assert task["confirmed"] is False
        assert task["expireAt"] > task["scheduledAt"], "确认窗口必须在提醒时间之后"


def test_today_tasks_are_sorted_by_time(user, plan_with_tasks):
    _, tasks = plan_with_tasks

    scheduled = [task["scheduledAt"] for task in tasks]
    assert scheduled == sorted(scheduled)


def test_repeated_today_call_does_not_duplicate_tasks(user, plan_with_tasks):
    """按需生成必须幂等：刷新几次页面不能变出成倍的任务。"""
    _, first = plan_with_tasks

    second = _today_tasks(user)

    assert len(second) == len(first)


def test_paused_plan_generates_no_tasks(user, medicine):
    plan = _create_plan(user, medicine["id"])
    ok(user.client.post(f"/api/plans/{plan['id']}/pause"))

    assert _today_tasks(user) == [], "暂停的计划不应再生成提醒"


def test_confirm_taken_marks_task_confirmed(user, plan_with_tasks):
    _, tasks = plan_with_tasks

    data = ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))

    assert data["status"] == "CONFIRMED"
    assert data["confirmed"] is True
    assert data["action"] == "TAKEN"


def test_confirm_is_idempotent(user, plan_with_tasks):
    """重复确认返回首次结果，不报错、不产生第二条记录。

    这是防「手抖点两下」和「网络重试」的必备设计，也是最容易被写成非幂等的地方。
    """
    _, tasks = plan_with_tasks
    task_id = tasks[0]["id"]

    first = ok(user.client.post(f"/api/reminders/{task_id}/confirm", json={"action": "TAKEN"}))
    second = ok(user.client.post(f"/api/reminders/{task_id}/confirm", json={"action": "SKIPPED"}))

    assert second["status"] == first["status"] == "CONFIRMED"
    assert second["action"] == "TAKEN", "重复确认不应覆盖首次结果"

    records = [r for r in ok(user.client.get("/api/records")) if r["taskId"] == task_id]
    assert len(records) == 1, "同一任务只能有一条服药记录"


def test_confirm_delayed_keeps_task_open(user, plan_with_tasks):
    """「稍后提醒」不是完成态：任务仍是 TRIGGERED，并记下顺延分钟数。"""
    _, tasks = plan_with_tasks
    task_id = tasks[0]["id"]

    data = ok(
        user.client.post(
            f"/api/reminders/{task_id}/confirm", json={"action": "DELAYED", "delayMinutes": 10}
        )
    )

    assert data["status"] == "TRIGGERED"
    assert data["confirmed"] is False, "稍后提醒不算已服药"
    assert data["action"] == "DELAYED"

    records = [r for r in ok(user.client.get("/api/records")) if r["taskId"] == task_id]
    assert records[0]["delayMinutes"] == 10


@pytest.mark.xfail(
    strict=False,
    reason="已知缺陷：稍后提醒把确认窗口改成 now+delay+窗口，"
    "当原提醒时间还在较远的未来时，新窗口反而比原来的短（待后端修为取两者较大值）",
)
def test_delay_does_not_shorten_the_confirmation_window(user, plan_with_tasks):
    """顺延之后，患者可确认的时间不该比之前更短。"""
    _, tasks = plan_with_tasks
    original_expire = tasks[0]["expireAt"]

    data = ok(
        user.client.post(
            f"/api/reminders/{tasks[0]['id']}/confirm",
            json={"action": "DELAYED", "delayMinutes": 10},
        )
    )

    assert data["expireAt"] >= original_expire


def test_confirm_skipped_records_reason(user, plan_with_tasks):
    _, tasks = plan_with_tasks
    task_id = tasks[1]["id"]

    data = ok(
        user.client.post(
            f"/api/reminders/{task_id}/confirm",
            json={"action": "SKIPPED", "skipReason": "外出忘带药"},
        )
    )

    assert data["status"] == "CONFIRMED"
    assert data["action"] == "SKIPPED"

    records = [r for r in ok(user.client.get("/api/records")) if r["taskId"] == task_id]
    assert records[0]["skipReason"] == "外出忘带药"


@pytest.mark.parametrize("action", ["EATEN", "taken", "", "TAKEN "])
def test_confirm_rejects_unknown_action(user, plan_with_tasks, action):
    """枚举值必须严格匹配，大小写和空格都不放过 —— 否则「非法操作被当成已服用」。"""
    _, tasks = plan_with_tasks

    expect_error(
        user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": action}), 400
    )


def test_confirm_requires_action(user, plan_with_tasks):
    _, tasks = plan_with_tasks

    expect_error(
        user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={}), 400, "操作类型不能为空"
    )


@pytest.mark.parametrize(
    "delay_minutes, message",
    [(0, "稍后时间至少1分钟"), (121, "稍后时间最多120分钟"), (-5, "稍后时间至少1分钟")],
)
def test_delay_minutes_must_be_within_window(user, plan_with_tasks, delay_minutes, message):
    _, tasks = plan_with_tasks

    expect_error(
        user.client.post(
            f"/api/reminders/{tasks[0]['id']}/confirm",
            json={"action": "DELAYED", "delayMinutes": delay_minutes},
        ),
        400,
        message,
    )


def test_confirm_defaults_delay_to_15_minutes(user, plan_with_tasks):
    """不传 delayMinutes 时后端按 15 分钟处理，这个默认值要写进契约，不能被悄悄改掉。"""
    _, tasks = plan_with_tasks
    task_id = tasks[0]["id"]

    ok(user.client.post(f"/api/reminders/{task_id}/confirm", json={"action": "DELAYED"}))

    records = [r for r in ok(user.client.get("/api/records")) if r["taskId"] == task_id]
    assert records[0]["delayMinutes"] == 15


def test_other_user_cannot_confirm_someone_elses_task(user, other_user, plan_with_tasks):
    _, tasks = plan_with_tasks

    expect_error(
        other_user.client.post(
            f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}
        ),
        403,
        "提醒任务不存在或无权操作",
    )


def test_confirm_nonexistent_task(user):
    expect_error(
        user.client.post("/api/reminders/99999999/confirm", json={"action": "TAKEN"}),
        403,
        "提醒任务不存在或无权操作",
    )


def test_records_expose_medicine_name(user, medicine, plan_with_tasks):
    """服药记录页要直接显示药名，不能让前端拿 taskId 再查一次。"""
    _, tasks = plan_with_tasks
    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))

    records = ok(user.client.get("/api/records"))

    assert records
    assert records[0]["medicineName"] == medicine["name"]
    assert records[0]["actionTime"]


def test_records_are_newest_first(user, plan_with_tasks):
    _, tasks = plan_with_tasks
    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))
    ok(user.client.post(f"/api/reminders/{tasks[1]['id']}/confirm", json={"action": "TAKEN"}))

    records = ok(user.client.get("/api/records"))

    times = [r["actionTime"] for r in records]
    assert times == sorted(times, reverse=True), "服药记录应按时间倒序"


def test_delayed_task_can_be_confirmed_again(user, plan_with_tasks):
    """「稍后提醒」之后再次确认，应更新同一条记录而不是新增一条。"""
    _, tasks = plan_with_tasks
    task_id = tasks[0]["id"]
    ok(user.client.post(f"/api/reminders/{task_id}/confirm", json={"action": "DELAYED", "delayMinutes": 5}))

    data = ok(user.client.post(f"/api/reminders/{task_id}/confirm", json={"action": "TAKEN"}))

    assert data["status"] == "CONFIRMED"
    records = [r for r in ok(user.client.get("/api/records")) if r["taskId"] == task_id]
    assert len(records) == 1
    assert records[0]["action"] == "TAKEN"


def test_single_time_plan_creates_one_task(user, medicine):
    plan = _create_plan(user, medicine["id"], times=[future_remind_time(40)])

    tasks = _today_tasks(user)

    assert len(tasks) == 1
    assert tasks[0]["planId"] == plan["id"]
