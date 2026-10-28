"""药品档案 CRUD 与横向越权。

越权（水平权限）是这类系统最容易漏的地方：接口都加了登录校验，
但如果查询没带 user_id 条件，A 登录后能直接改 B 的药品。
这组用例专门盯这一条。
"""

import pytest

from api.client import expect_error, ok


def test_create_returns_record_owned_by_current_user(user):
    data = ok(
        user.client.post(
            "/api/medicines",
            json={"name": "二甲双胍", "specification": "0.5g", "dosage": "1片", "unit": "片"},
        )
    )

    assert data["id"] > 0
    assert data["userId"] == user.user_id, "药品必须归属当前登录用户，不能由请求体指定"
    assert data["name"] == "二甲双胍"


def test_create_defaults_enabled_to_1(user):
    data = ok(user.client.post("/api/medicines", json={"name": "默认启用药品"}))

    assert data["enabled"] == 1


def test_create_ignores_user_id_in_request_body(user, other_user):
    """请求体里塞 userId 不能把药品挂到别人名下。"""
    data = ok(
        user.client.post(
            "/api/medicines", json={"name": "越权尝试", "userId": other_user.user_id}
        )
    )

    assert data["userId"] == user.user_id


def test_list_contains_created_medicine(user, medicine):
    data = ok(user.client.get("/api/medicines"))

    ids = [item["id"] for item in data]
    assert medicine["id"] in ids


def test_list_only_returns_own_medicines(user, other_user):
    mine = ok(user.client.post("/api/medicines", json={"name": "我的药"}))

    theirs = ok(other_user.client.get("/api/medicines"))

    assert mine["id"] not in [item["id"] for item in theirs]


def test_get_by_id(user, medicine):
    data = ok(user.client.get(f"/api/medicines/{medicine['id']}"))

    assert data["id"] == medicine["id"]
    assert data["name"] == medicine["name"]


def test_update_changes_fields(user, medicine):
    data = ok(
        user.client.put(
            f"/api/medicines/{medicine['id']}",
            json={"name": "阿司匹林（改名后）", "unit": "粒", "remark": "睡前服用", "enabled": 0},
        )
    )

    assert data["name"] == "阿司匹林（改名后）"
    assert data["unit"] == "粒"
    assert data["enabled"] == 0

    reread = ok(user.client.get(f"/api/medicines/{medicine['id']}"))
    assert reread["name"] == "阿司匹林（改名后）", "修改应真正落库，不能只回显"


def test_delete_then_get_returns_forbidden(user, medicine):
    ok(user.client.delete(f"/api/medicines/{medicine['id']}"))

    expect_error(
        user.client.get(f"/api/medicines/{medicine['id']}"), 403, "药品不存在或无权查看"
    )


def test_delete_is_not_repeatable(user, medicine):
    ok(user.client.delete(f"/api/medicines/{medicine['id']}"))

    expect_error(
        user.client.delete(f"/api/medicines/{medicine['id']}"), 403, "药品不存在或无权删除"
    )


def test_deleted_medicine_disappears_from_list(user, medicine):
    ok(user.client.delete(f"/api/medicines/{medicine['id']}"))

    data = ok(user.client.get("/api/medicines"))

    assert medicine["id"] not in [item["id"] for item in data]


def test_create_without_name_is_rejected(user):
    expect_error(user.client.post("/api/medicines", json={"unit": "片"}), 400, "药品名称不能为空")


@pytest.mark.parametrize(
    "field, limit",
    [("name", 128), ("specification", 64), ("dosage", 64), ("unit", 16), ("remark", 255)],
)
def test_create_rejects_overlong_field(user, field, limit):
    """超长字段应被拦住，而不是在数据库层截断或报 500。"""
    payload = {"name": "长度校验药品"}
    payload[field] = "长" * (limit + 1)

    expect_error(user.client.post("/api/medicines", json=payload), 400)


def test_create_accepts_field_at_exact_limit(user):
    """边界值取到上限本身必须通过 —— 校验写 > 还是 >= 很容易搞错。"""
    data = ok(user.client.post("/api/medicines", json={"name": "长" * 128}))

    assert len(data["name"]) == 128


def test_get_nonexistent_medicine(user):
    expect_error(user.client.get("/api/medicines/99999999"), 403, "药品不存在或无权查看")


def test_other_user_cannot_read_medicine(other_user, medicine):
    expect_error(
        other_user.client.get(f"/api/medicines/{medicine['id']}"), 403, "药品不存在或无权查看"
    )


def test_other_user_cannot_update_medicine(other_user, medicine):
    expect_error(
        other_user.client.put(
            f"/api/medicines/{medicine['id']}", json={"name": "被别人改掉的名字"}
        ),
        403,
        "药品不存在或无权修改",
    )


def test_other_user_cannot_delete_medicine(other_user, medicine):
    expect_error(
        other_user.client.delete(f"/api/medicines/{medicine['id']}"),
        403,
        "药品不存在或无权删除",
    )


def test_other_user_write_is_rejected_and_data_unchanged(user, other_user, medicine):
    """越权写被拒后，数据必须保持原样 —— 防止「报错了但已经改了一半」。"""
    original = medicine["name"]

    other_user.client.put(f"/api/medicines/{medicine['id']}", json={"name": "篡改"})
    other_user.client.delete(f"/api/medicines/{medicine['id']}")

    current = ok(user.client.get(f"/api/medicines/{medicine['id']}"))
    assert current["name"] == original
