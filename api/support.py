"""用例共用的小工具：账号名生成、提醒时间点计算。"""

from __future__ import annotations

import datetime
import uuid

import pytest

# 只给测试库用的固定口令，不是任何真实账号的密码。
TEST_PASSWORD = "MedTest!2026"


def unique_account(prefix: str = "t") -> str:
    """生成唯一账号。

    后端校验规则是 ^[a-zA-Z0-9_]{4,32}$，所以只用十六进制字符拼接。
    每个用例都用新账号，用例之间就不会互相看到对方的数据，
    也不需要「跑前清库」这种脆弱的前置步骤。
    """
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def today() -> datetime.date:
    return datetime.date.today()


def future_remind_time(minutes_ahead: int = 30) -> str:
    """返回一个「今天稍后」的提醒时间点，格式 HH:MM。

    为什么必须取未来时间：后端生成当天任务时会跳过
    「计划里早于计划最后修改时间」的时间点（避免改完计划又补出一堆已过期的任务）。
    如果这里给 08:00 这种已经过去的时间，今天的任务列表会是空的，
    后面的确认用例就全部无对象可测。

    跨零点的情况没有可用的未来时间点，直接跳过而不是写一个会莫名失败的用例。
    """
    now = datetime.datetime.now()
    target = now + datetime.timedelta(minutes=minutes_ahead)
    if target.date() != now.date():
        pytest.skip("当前时间距零点不足，今天已无法生成「稍后」的提醒时间点，跳过")
    return target.strftime("%H:%M")


def future_remind_times(count: int = 2, start_minutes: int = 30, step: int = 20) -> list[str]:
    """返回 count 个互不相同、且都在今天的提醒时间点。"""
    return [future_remind_time(start_minutes + i * step) for i in range(count)]
