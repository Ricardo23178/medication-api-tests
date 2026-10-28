"""pytest 全局夹具。

三个约定：
1. 每个用例用**新注册的账号**，数据互不可见，因此不需要清库、不依赖执行顺序。
2. 用例断言的是「接口契约」，不是「数据库里恰好有什么」——
   所以不假设任何预置数据，全部由用例自己建。
3. 业务错误走 body.code，鉴权错误走真实 HTTP 状态码，两种断言工具见 api/client.py。
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import pytest
import requests

from api.client import ApiClient, ok
from api.support import TEST_PASSWORD, unique_account

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_BASE_URL = "http://127.0.0.1:8080"


def _load_dotenv() -> None:
    """读项目根目录的 .env，只补齐缺失的变量。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class UserSession:
    """一个已登录身份：账号、token、以及带好 token 的客户端。"""

    account: str
    password: str
    user_id: int
    nickname: str
    token: str
    client: ApiClient


@pytest.fixture(scope="session")
def base_url() -> str:
    _load_dotenv()
    return os.environ.get("MED_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session", autouse=True)
def _service_ready(base_url: str) -> None:
    """开跑前确认被测服务活着。

    不做这一步的话，服务没启动时每个用例都会在连接错误上炸开，
    几十条红色报错里看不出真正原因。这里一次性给出可执行的提示。
    """
    try:
        resp = requests.get(f"{base_url}/api/health", timeout=5)
        resp.raise_for_status()
        body = resp.json()
        assert body.get("status") == "ok"
    except Exception as exc:  # noqa: BLE001 - 任何原因都归为「没起来」
        pytest.exit(
            f"被测服务未就绪：{base_url}/api/health 访问失败（{exc}）。\n"
            f"1) python scripts/prepare_db.py   重建测试库\n"
            f"2) 用测试库启动 medication-backend（见 README「三步跑起来」）\n"
            f"3) 确认端口与 .env 里的 MED_API_BASE_URL 一致",
            returncode=2,
        )


@pytest.fixture
def anon(base_url: str) -> ApiClient:
    """不带 token 的客户端，用来测「未登录被拦」。"""
    return ApiClient(base_url)


@pytest.fixture
def user_factory(base_url: str):
    """注册新用户并返回已登录身份。

    走公开的 /api/auth/register，不直接插库 —— 这样夹具本身
    也顺便验证了「注册即登录」这条链路是通的。
    """

    def _create(nickname: str = "测试用户", phone: str | None = None) -> UserSession:
        account = unique_account()
        payload = {
            "account": account,
            "password": TEST_PASSWORD,
            "confirmPassword": TEST_PASSWORD,
            "nickname": nickname,
        }
        if phone is not None:
            payload["phone"] = phone
        data = ok(ApiClient(base_url).post("/api/auth/register", json=payload))
        return UserSession(
            account=account,
            password=TEST_PASSWORD,
            user_id=data["user"]["id"],
            nickname=nickname,
            token=data["token"],
            client=ApiClient(base_url, token=data["token"]),
        )

    return _create


@pytest.fixture
def user(user_factory) -> UserSession:
    return user_factory("主用户")


@pytest.fixture
def other_user(user_factory) -> UserSession:
    """第二个独立账号，专门用来验证越权访问被挡住。"""
    return user_factory("旁观者")


@pytest.fixture
def medicine(user: UserSession) -> dict:
    """当前用户名下的一盒药，供计划相关的用例使用。"""
    return ok(
        user.client.post(
            "/api/medicines",
            json={
                "name": "阿司匹林肠溶片",
                "specification": "100mg×30片",
                "dosage": "1片",
                "unit": "片",
                "remark": "饭后服用",
            },
        )
    )
