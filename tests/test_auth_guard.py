"""鉴权边界：谁能进、谁不能进。

这一层的特殊之处在于：鉴权失败是拦截器直接写响应，**会真的返回 401/403**，
而业务错误仍然保持 HTTP 200。两种断言工具不能混用，
否则会出现「状态码断言过了、其实被拦在门外」的假通过。
"""

import pytest

from api.client import expect_http, ok
from api.support import unique_account

PROTECTED_ENDPOINTS = [
    ("GET", "/api/user/me"),
    ("GET", "/api/medicines"),
    ("GET", "/api/plans"),
    ("GET", "/api/reminders/today"),
    ("GET", "/api/statistics/calendar"),
    ("GET", "/api/family/relations"),
    ("GET", "/api/records"),
]


@pytest.mark.parametrize("method, path", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_anonymous(anon, method, path):
    resp = anon.request(method, path)

    payload = expect_http(resp, 401)
    assert payload["code"] == 401
    assert "未登录" in payload["message"]


def test_missing_authorization_header_is_401(anon):
    expect_http(anon.get("/api/user/me"), 401)


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",  # 只有前缀没有 token
        "Basic dXNlcjpwYXNz",  # 错误的认证方案
        "Bearer not-a-real-token",
        "Bearer a.b.c",
    ],
)
def test_malformed_credential_is_401(anon, header):
    resp = anon.get("/api/user/me", headers={"Authorization": header})

    expect_http(resp, 401)


def test_valid_token_identifies_current_user(user):
    """凭 token 认人：返回的 id 必须就是 token 里的那个用户，而不是随便一个。"""
    data = ok(user.client.get("/api/user/me"))

    assert data["id"] == user.user_id
    assert data["role"] == "USER"


def test_token_of_one_user_does_not_see_another_users_identity(user, other_user):
    mine = ok(user.client.get("/api/user/me"))

    assert mine["id"] == user.user_id
    assert mine["id"] != other_user.user_id


@pytest.mark.parametrize(
    "path",
    ["/api/admin/me", "/api/admin/overview", "/api/admin/users", "/api/admin/settings"],
)
def test_normal_user_is_forbidden_from_admin_api(user, path):
    """普通用户访问管理端返回 403，不是 401。

    401 的语义是「你还没证明你是谁」，403 是「证明过了，但没这个权限」。
    两者混淆会让客户端无法决定该跳登录页还是提示无权限。
    """
    resp = user.client.get(path)

    payload = expect_http(resp, 403)
    assert payload["code"] == 403
    assert "管理员" in payload["message"]


def test_admin_api_also_rejects_anonymous(anon):
    """未登录访问管理端应该是 401（先证明身份），不是直接 403。"""
    expect_http(anon.get("/api/admin/me"), 401)


def test_health_and_login_are_public(anon, user):
    """三个入口必须免登录：健康检查、登录、注册。"""
    account = unique_account()
    assert anon.get("/api/health").status_code == 200
    assert anon.post(
        "/api/auth/login", json={"account": user.account, "password": user.password}
    ).status_code == 200
    assert anon.post(
        "/api/auth/register",
        json={
            "account": account,
            "password": "MedTest!2026",
            "confirmPassword": "MedTest!2026",
            "nickname": "公开入口",
        },
    ).status_code == 200
