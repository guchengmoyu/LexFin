"""认证接口测试（docs/09 §4.1）：重复注册 409 / 错误密码 40103 / 无 token 40100 /
篡改 token 40102 / 角色越权 40300。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


async def test_register_and_duplicate(client):
    payload = {
        "username": "it_user_001",
        "password": "Passw0rd",
        "real_name": "集成测试",
    }
    r1 = await client.post(f"{API}/auth/register", json=payload)
    assert r1.status_code == 200
    body = r1.json()
    assert body["code"] == 0
    assert body["data"]["role"] == "viewer"
    assert "password_hash" not in r1.text

    r2 = await client.post(f"{API}/auth/register", json=payload)
    assert r2.status_code == 409
    assert r2.json()["code"] == 40900


async def test_login_wrong_password(client):
    await client.post(
        f"{API}/auth/register",
        json={"username": "it_user_002", "password": "Passw0rd"},
    )
    r = await client.post(
        f"{API}/auth/login", json={"username": "it_user_002", "password": "Wrong000"}
    )
    assert r.status_code == 401
    assert r.json()["code"] == 40103


async def test_no_token(client):
    r = await client.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == 40100


async def test_tampered_token(client):
    r = await client.get(
        f"{API}/auth/me", headers={"Authorization": "Bearer invalid.token.value"}
    )
    assert r.status_code == 401
    assert r.json()["code"] == 40102


async def test_role_forbidden(client):
    """viewer 角色调用 admin 接口 → 40300（docs/09 §4.1 角色越权）。"""
    await client.post(
        f"{API}/auth/register",
        json={"username": "it_viewer_001", "password": "Passw0rd"},
    )
    login = await client.post(
        f"{API}/auth/login", json={"username": "it_viewer_001", "password": "Passw0rd"}
    )
    token = login.json()["data"]["access_token"]
    r = await client.post(
        f"{API}/kb",
        json={"code": "it_kb", "name": "集成测试库", "category": "banking"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == 40300


async def test_me_response_shape(auth_client):
    r = await auth_client.get(f"{API}/auth/me")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    assert "password_hash" not in r.text
