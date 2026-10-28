"""用药日历与完成率统计。

这里有一个必须写清楚的**统计口径**，也是最容易被答不上来的追问：

    应完成 shouldCount  = 当天的提醒任务数
    已服   takenCount   = action=TAKEN 的记录数
    跳过   skippedCount = action=SKIPPED 的记录数
    未确认 unconfirmed  = should - taken - skipped
    稍后   delayedCount = action=DELAYED 的记录数（**与未确认有重叠**）

所以恒等式是：should == taken + skipped + unconfirmed，
而 delayed 是「未确认」里的一个子类 —— 四项相加会比应完成数多，这是口径问题不是 bug。
用例把这两条都锁住，将来谁改了算法都会立刻暴露。
"""

import datetime

from api.client import expect_error, ok
from api.support import future_remind_times, today


def _range(user, start=None, end=None):
    params = {}
    if start is not None:
        params["startDate"] = start
    if end is not None:
        params["endDate"] = end
    return ok(user.client.get("/api/statistics/calendar", params=params))


def _today_stat(user):
    day = today().isoformat()
    data = _range(user, day, day)
    assert len(data["days"]) == 1
    return data["days"][0]


def _create_plan(user, medicine_id, times=None):
    return ok(
        user.client.post(
            "/api/plans",
            json={
                "medicineId": medicine_id,
                "dosagePerTime": 1,
                "dosageUnit": "片",
                "startDate": today().isoformat(),
                "remindTimes": times or future_remind_times(2),
            },
        )
    )


def test_default_range_covers_last_30_days(user):
    data = _range(user)

    start = datetime.date.fromisoformat(data["startDate"])
    end = datetime.date.fromisoformat(data["endDate"])
    assert end == today(), "默认区间应结束于今天"
    assert (end - start).days == 29, "默认是最近 30 天（含今天）"
    assert len(data["days"]) == 30


def test_explicit_range_returns_one_entry_per_day(user):
    start = today() - datetime.timedelta(days=6)
    data = _range(user, start.isoformat(), today().isoformat())

    assert len(data["days"]) == 7
    assert data["days"][0]["date"] == start.isoformat()
    assert data["days"][-1]["date"] == today().isoformat()


def test_empty_range_has_zero_counts(user):
    """没有任何任务时应返回 0，而不是 null 或 500。"""
    day = _today_stat(user)

    assert day["shouldCount"] == 0
    assert day["takenCount"] == 0
    assert day["unconfirmedCount"] == 0
    assert day["completionRate"] == 0.0


def test_invalid_date_format_is_rejected(user):
    expect_error(
        user.client.get("/api/statistics/calendar", params={"startDate": "2026-13-45"}),
        400,
        "请求参数格式不正确",
    )


def test_start_after_end_is_rejected(user):
    expect_error(
        user.client.get(
            "/api/statistics/calendar",
            params={"endDate": "2026-10-01", "startDate": "2026-10-10"},
        ),
        400,
        "统计日期范围必须按先后顺序",
    )


def test_confirming_a_task_moves_completion_rate(user, medicine):
    """完整的闭环：建计划 → 生成任务 → 确认 → 统计里的完成率变成 100%。"""
    _create_plan(user, medicine["id"], times=future_remind_times(1))
    tasks = ok(user.client.get("/api/reminders/today"))
    assert len(tasks) == 1

    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))

    day = _today_stat(user)
    assert day["shouldCount"] == 1
    assert day["takenCount"] == 1
    assert day["unconfirmedCount"] == 0
    assert day["completionRate"] == 100.0


def test_skipped_task_is_not_counted_as_taken(user, medicine):
    _create_plan(user, medicine["id"], times=future_remind_times(1))
    tasks = ok(user.client.get("/api/reminders/today"))
    ok(
        user.client.post(
            f"/api/reminders/{tasks[0]['id']}/confirm",
            json={"action": "SKIPPED", "skipReason": "医生让停药"},
        )
    )

    day = _today_stat(user)
    assert day["skippedCount"] == 1
    assert day["takenCount"] == 0
    assert day["unconfirmedCount"] == 0
    assert day["completionRate"] == 0.0


def test_delayed_task_stays_unconfirmed(user, medicine):
    """稍后提醒不算完成：既不进 taken，也仍然留在 unconfirmed 里。"""
    _create_plan(user, medicine["id"], times=future_remind_times(1))
    tasks = ok(user.client.get("/api/reminders/today"))
    ok(
        user.client.post(
            f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "DELAYED", "delayMinutes": 10}
        )
    )

    day = _today_stat(user)
    assert day["delayedCount"] == 1
    assert day["takenCount"] == 0
    assert day["unconfirmedCount"] == 1
    assert day["completionRate"] == 0.0


def test_counters_obey_named_invariant(user, medicine):
    """恒等式：应完成 = 已服 + 跳过 + 未确认（稍后是未确认的子集，不单独扣减）。"""
    _create_plan(user, medicine["id"], times=future_remind_times(3, start_minutes=30, step=10))
    tasks = ok(user.client.get("/api/reminders/today"))
    assert len(tasks) == 3

    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))
    ok(user.client.post(f"/api/reminders/{tasks[1]['id']}/confirm", json={"action": "SKIPPED"}))
    ok(
        user.client.post(
            f"/api/reminders/{tasks[2]['id']}/confirm", json={"action": "DELAYED", "delayMinutes": 5}
        )
    )

    day = _today_stat(user)
    assert day["takenCount"] == 1
    assert day["skippedCount"] == 1
    assert day["delayedCount"] == 1
    assert day["unconfirmedCount"] == 1
    assert day["shouldCount"] == day["takenCount"] + day["skippedCount"] + day["unconfirmedCount"]
    assert day["delayedCount"] <= day["unconfirmedCount"], "稍后属于未确认的一部分"


def test_summary_equals_sum_of_days(user, medicine):
    _create_plan(user, medicine["id"], times=future_remind_times(1))
    tasks = ok(user.client.get("/api/reminders/today"))
    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))

    start = today() - datetime.timedelta(days=3)
    data = _range(user, start.isoformat(), today().isoformat())
    summary = data["summary"]

    pairs = {
        "totalShould": "shouldCount",
        "totalTaken": "takenCount",
        "totalDelayed": "delayedCount",
        "totalSkipped": "skippedCount",
        "totalUnconfirmed": "unconfirmedCount",
    }
    for total_field, day_field in pairs.items():
        expected = sum(day[day_field] for day in data["days"])
        assert summary[total_field] == expected, f"{total_field} 应等于按天 {day_field} 之和"


def test_statistics_are_isolated_per_user(user, other_user, medicine):
    """统计只算自己的任务，别人吃药不能拉高我的完成率。"""
    _create_plan(user, medicine["id"], times=future_remind_times(1))
    tasks = ok(user.client.get("/api/reminders/today"))
    ok(user.client.post(f"/api/reminders/{tasks[0]['id']}/confirm", json={"action": "TAKEN"}))

    mine = _today_stat(user)
    theirs = _today_stat(other_user)

    assert mine["shouldCount"] == 1
    assert theirs["shouldCount"] == 0, "旁人的统计不该被我的数据污染"
