"""家属协同：邀请码绑定、授权范围、解绑，以及「谁能看谁的异常」。

这条链路的设计要点是「绑定是双向的、解绑是单向的」：
owner 发起邀请、家属凭码接受；解绑由 owner 单方面完成，
解绑后家属立刻失去查看权限，连关系记录都看不到。
"""

import pytest

from api.client import expect_error, ok


def _invite(user, **payload):
    return ok(user.client.post("/api/family/invitations", json=payload))


def _accept(user, code):
    return user.client.post("/api/family/invitations/accept", json={"inviteCode": code})


def test_invite_creates_pending_relation(user):
    relation = _invite(user)

    assert relation["relationStatus"] == "PENDING"
    assert relation["ownerUserId"] == user.user_id
    assert relation["familyUserId"] is None, "接受之前还没有绑定具体家属"
    assert relation["inviteCode"], "必须下发邀请码，否则家属无从接受"
    assert relation["inviteExpireAt"], "邀请码要有有效期"


def test_invite_code_has_reasonable_length(user):
    """邀请码太短会被暴力猜解，太长则老人念不出来。这里锁住 6-12 位。"""
    code = _invite(user)["inviteCode"]

    assert 6 <= len(code) <= 12


def test_invite_defaults_to_both_scopes(user):
    """不指定范围时默认同时授权「计划状态」与「异常事件」。"""
    relation = _invite(user)

    scopes = set(relation["scope"].split(","))
    assert scopes == {"PLAN_STATUS", "ABNORMAL_EVENT"}


def test_invite_accepts_explicit_scope(user):
    relation = _invite(user, scope="ABNORMAL_EVENT")

    assert relation["scope"] == "ABNORMAL_EVENT"


@pytest.mark.parametrize("scope", ["ALL", "PLAN_STATUS,ALL", "plan_status", "ABNORMAL_EVENT,"])
def test_invite_rejects_unknown_scope(user, scope):
    expect_error(
        user.client.post("/api/family/invitations", json={"scope": scope}),
        400,
        "授权范围只能为",
    )


def test_accept_activates_relation(user, other_user):
    relation = _invite(user)

    data = ok(_accept(other_user, relation["inviteCode"]))

    assert data["relationStatus"] == "ACTIVE"
    assert data["familyUserId"] == other_user.user_id
    assert data["familyNickname"] == other_user.nickname
    assert data["ownerNickname"] == user.nickname
    assert data["bindTime"]
    assert data["inviteCode"] is None, "绑定成功后邀请码应被消费掉，不能留着二次使用"


def test_accept_unknown_code(other_user):
    expect_error(_accept(other_user, "NOSUCHCD"), 400, "邀请码不存在")


def test_owner_cannot_accept_own_invite(user):
    """自己绑自己会让「家属」和「患者」变成同一个账号，权限模型失去意义。"""
    relation = _invite(user)

    expect_error(_accept(user, relation["inviteCode"]), 400, "不能绑定自己")


def test_invite_code_cannot_be_used_twice(user, other_user, user_factory):
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))
    third = user_factory("第三个人")

    expect_error(_accept(third, relation["inviteCode"]), 400, "邀请码不存在")


def test_relation_is_visible_from_both_sides(user, other_user):
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    owner_view = ok(user.client.get("/api/family/relations"))
    family_view = ok(other_user.client.get("/api/family/relations"))

    assert [r["id"] for r in owner_view if r["relationStatus"] == "ACTIVE"] == [relation["id"]]
    assert [r["id"] for r in family_view if r["relationStatus"] == "ACTIVE"] == [relation["id"]]


def test_unrelated_user_sees_no_relations(user, other_user):
    _invite(user)

    assert ok(other_user.client.get("/api/family/relations")) == []


def test_pending_invite_does_not_grant_access(user, other_user, user_factory):
    """发了邀请但对方还没接受时，任何人都不该拿到临时权限。"""
    third = user_factory("路人")
    _invite(user)

    assert ok(third.client.get("/api/family/abnormal-events")) == []


def test_non_owner_cannot_unbind(user, other_user):
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    expect_error(
        other_user.client.delete(f"/api/family/relations/{relation['id']}"),
        403,
        "关系不存在、已解除或无权操作",
    )


def test_owner_unbind_revokes_family_access(user, other_user):
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    ok(user.client.delete(f"/api/family/relations/{relation['id']}"))

    owner_view = ok(user.client.get("/api/family/relations"))
    revoked = [r for r in owner_view if r["id"] == relation["id"]][0]
    assert revoked["relationStatus"] == "REVOKED"
    assert revoked["unbindTime"]

    family_view = ok(other_user.client.get("/api/family/relations"))
    assert relation["id"] not in [r["id"] for r in family_view], "解绑后家属连关系记录都看不到"


def test_unbind_is_not_repeatable(user):
    relation = _invite(user)
    ok(user.client.delete(f"/api/family/relations/{relation['id']}"))

    expect_error(
        user.client.delete(f"/api/family/relations/{relation['id']}"),
        403,
        "关系不存在、已解除或无权操作",
    )


def test_unbind_nonexistent_relation(user):
    expect_error(user.client.delete("/api/family/relations/99999999"), 403)


def test_abnormal_events_empty_before_any_timeout(user, other_user):
    """刚绑定、还没有超时任务时，异常事件应为空数组。"""
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    assert ok(other_user.client.get("/api/family/abnormal-events")) == []


def test_abnormal_events_support_include_closed_flag(user, other_user):
    """includeClosed 参数要被接受，并且在空数据下同样返回空数组。"""
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    data = ok(other_user.client.get("/api/family/abnormal-events", params={"includeClosed": "true"}))

    assert data == []


def test_family_cannot_handle_nonexistent_event(user, other_user):
    relation = _invite(user)
    ok(_accept(other_user, relation["inviteCode"]))

    expect_error(
        other_user.client.post("/api/family/abnormal-events/99999999/acknowledge"),
        403,
        "事件不存在或无权处理",
    )
