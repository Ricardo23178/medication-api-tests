"""健康检查：服务与数据库是否真的连通。

这是最小的一条用例，但价值在于：它能在所有业务用例失败时，
第一时间把「服务起没起来」和「业务有问题」区分开。

注意：/api/health 是全项目唯一**不套 Result 壳**的接口，
它直接返回 {status, serverTime, dbVersion, sysUserCount}，没有 code 字段。
所以这里不能用 ok() 断言，否则会误判成业务失败。
"""

import re

from api.client import body_of


def _health(anon) -> dict:
    return body_of(anon.get("/api/health"))


def test_health_returns_ok(anon):
    data = _health(anon)

    assert data["status"] == "ok"
    assert data["serverTime"]


def test_health_reports_real_database_connection(anon):
    """dbVersion 来自 SELECT VERSION()，能查出来说明数据源真的连上了。

    如果这里是一条假数据返回，后续所有用例都会在 MySQL 报错上炸开，
    所以这条断言值得单独存在。
    """
    data = _health(anon)

    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", data["dbVersion"]), (
        f"dbVersion 应是真实的 MySQL 版本号，实际 {data['dbVersion']!r}"
    )
    assert isinstance(data["sysUserCount"], int)
    assert data["sysUserCount"] >= 0


def test_health_is_reachable_without_token(anon):
    """健康检查必须免登录，否则运维探活无法使用。"""
    resp = anon.get("/api/health")

    assert resp.status_code == 200
