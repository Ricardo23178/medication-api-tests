"""注册与登录。

重点不只是「能注册成功」，而是几条安全边界：
账号唯一、密码不明文回传、注册不能自选角色、登录失败不泄露账号是否存在。
"""

import pytest

from api.client import expect_error, ok
from api.support import TEST_PASSWORD, unique_account


def _register_payload(**overrides):
    payload = {
        "account": unique_account(),
        "password": TEST_PASSWORD,
        "confirmPassword": TEST_PASSWORD,
        "nickname": "张阿姨",
    }
    payload.update(overrides)
    return payload


def test_register_returns_token_and_profile(anon):
    """注册即登录：不用再调一次登录接口。"""
    payload = _register_payload(phone="13800138000")
    data = ok(anon.post("/api/auth/register", json=payload))

    assert data["tokenType"] == "Bearer"
    assert data["token"], "注册应直接下发 token"
    assert data["expiresIn"] > 0
    assert data["user"]["account"] == payload["account"]
    assert data["user"]["nickname"] == payload["nickname"]
    assert isinstance(data["user"]["id"], int) and data["user"]["id"] > 0


def test_register_never_returns_password_hash(anon):
    """接口回传的用户信息里不能出现密码或哈希。"""
    data = ok(anon.post("/api/auth/register", json=_register_payload()))

    serialized = str(data["user"]).lower()
    assert "password" not in serialized
    assert "hash" not in serialized


def test_register_cannot_escalate_to_admin(anon):
    """多塞一个 role 字段也无效：后端把新账号硬编码为 USER。

    这是一条提权防护用例。补上它以后，将来若有人为了「方便」放开 role 入参，
    这条用例会立刻变红。
    """
    payload = _register_payload()
    payload["role"] = "ADMIN"

    data = ok(anon.post("/api/auth/register", json=payload))

    assert data["user"]["role"] == "USER"


def test_register_rejects_duplicate_account(anon, user):
    expect_error(
        anon.post(
            "/api/auth/register",
            json={
                "account": user.account,
                "password": TEST_PASSWORD,
                "confirmPassword": TEST_PASSWORD,
                "nickname": "重复注册",
            },
        ),
        400,
        "已被注册",
    )


def test_register_rejects_password_mismatch(anon):
    payload = _register_payload()
    payload["confirmPassword"] = TEST_PASSWORD + "x"

    expect_error(anon.post("/api/auth/register", json=payload), 400, "两次输入的密码不一致")


@pytest.mark.parametrize("password", ["12345", ""])
def test_register_rejects_short_password(anon, password):
    payload = _register_payload(password=password, confirmPassword=password)

    expect_error(anon.post("/api/auth/register", json=payload), 400)


@pytest.mark.parametrize("account", ["ab", "带中文的账号", "has space", "sym!bol"])
def test_register_rejects_illegal_account(anon, account):
    payload = _register_payload(account=account)

    expect_error(anon.post("/api/auth/register", json=payload), 400)


@pytest.mark.parametrize("phone", ["12345", "1380013800", "23800138000", "1380013800011"])
def test_register_rejects_illegal_phone(anon, phone):
    payload = _register_payload(phone=phone)

    expect_error(anon.post("/api/auth/register", json=payload), 400, "手机号格式不正确")


def test_register_allows_missing_phone(anon):
    """手机号是可选项，不填也能注册（空串不该落库成脏数据）。"""
    payload = _register_payload()
    payload.pop("phone", None)

    data = ok(anon.post("/api/auth/register", json=payload))

    assert data["token"]


def test_login_returns_token(anon, user):
    data = ok(anon.post("/api/auth/login", json={"account": user.account, "password": user.password}))

    assert data["token"]
    assert data["user"]["id"] == user.user_id


def test_login_wrong_password_does_not_leak_which_part_is_wrong(anon, user):
    """密码错与账号不存在必须返回同一句话，避免被用来枚举已注册账号。"""
    wrong_password = expect_error(
        anon.post("/api/auth/login", json={"account": user.account, "password": "WrongPass!1"}),
        401,
    )
    unknown_account = expect_error(
        anon.post("/api/auth/login", json={"account": unique_account(), "password": TEST_PASSWORD}),
        401,
    )

    assert wrong_password == unknown_account == "账号或密码错误"


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"account": "", "password": TEST_PASSWORD}, "账号不能为空"),
        ({"account": "someone"}, "密码不能为空"),
    ],
)
def test_login_requires_both_fields(anon, payload, expected):
    expect_error(anon.post("/api/auth/login", json=payload), 400, expected)
