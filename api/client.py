"""被测服务的 HTTP 客户端与断言工具。

这个项目有一条必须记住的约定：
    业务错误一律返回 **HTTP 200**，真正的成败放在响应体的 `code` 字段里
    （GlobalExceptionHandler 有意不改变状态码，前端只看 body.code）。
    只有拦截器层面的鉴权失败（过期 token、非管理员访问管理端）才会真的返回 401/403。

所以断言分两类，混用会写出「看起来过了其实是空过」的用例：
    ok(resp)            断言 HTTP 200 且 body.code == 200，返回 data
    expect_error(resp, code)  断言 HTTP 200 且 body.code == 期望值，返回 message
    expect_http(resp, status) 断言真实 HTTP 状态码（只用于鉴权层）
"""

from __future__ import annotations

from typing import Any

import requests


class ApiClient:
    """薄封装：基地址 + 可选 token，一个实例代表一个身份。"""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self._session.request(method, self.base_url + path, **kwargs)

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)


def body_of(resp: requests.Response) -> dict[str, Any]:
    """取出 JSON 响应体；不是 JSON 时给出可读的失败信息，而不是 JSONDecodeError。"""
    try:
        parsed = resp.json()
    except ValueError:
        snippet = resp.text[:300] if resp.text else "<空响应>"
        raise AssertionError(
            f"响应不是合法 JSON：HTTP {resp.status_code} {resp.request.method} "
            f"{resp.request.url}\n{snippet}"
        ) from None
    assert isinstance(parsed, dict), f"响应体应为 JSON 对象，实际是 {type(parsed).__name__}"
    return parsed


def ok(resp: requests.Response) -> Any:
    """断言业务成功，返回 data。"""
    payload = body_of(resp)
    assert resp.status_code == 200, (
        f"应为 HTTP 200，实际 {resp.status_code}："
        f"code={payload.get('code')} message={payload.get('message')}"
    )
    assert payload.get("code") == 200, (
        f"业务码应为 200，实际 code={payload.get('code')} "
        f"message={payload.get('message')}（{resp.request.method} {resp.request.url}）"
    )
    return payload.get("data")


def expect_error(
    resp: requests.Response, code: int, message_contains: str | None = None
) -> str:
    """断言业务失败码，返回 message 便于继续断言文案。"""
    payload = body_of(resp)
    assert resp.status_code == 200, (
        f"业务失败应保持 HTTP 200（本项目约定），实际 {resp.status_code}"
    )
    assert payload.get("code") == code, (
        f"业务码应为 {code}，实际 {payload.get('code')} "
        f"message={payload.get('message')}（{resp.request.method} {resp.request.url}）"
    )
    message = payload.get("message") or ""
    if message_contains is not None:
        assert message_contains in message, f"错误提示应包含 {message_contains!r}，实际 {message!r}"
    return message


def expect_http(resp: requests.Response, status: int) -> dict[str, Any]:
    """断言真实 HTTP 状态码（鉴权层用），返回响应体。"""
    payload = body_of(resp)
    assert resp.status_code == status, (
        f"应为 HTTP {status}，实际 {resp.status_code}：{payload}"
    )
    return payload
