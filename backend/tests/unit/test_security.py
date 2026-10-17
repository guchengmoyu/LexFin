"""安全模块单元测试（docs/09 test_security）。

覆盖：bcrypt 哈希/校验、JWT 签发/解码/篡改/过期、用户名与密码校验规则。
"""
from __future__ import annotations

import pytest

from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)


# --------------------------------------------------------------------------- #
#  bcrypt 密码
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_hash_and_verify_password():
    hashed = hash_password("Passw0rd!2025")
    assert hashed.startswith("$2"), "应为 bcrypt 哈希"
    assert verify_password("Passw0rd!2025", hashed)
    assert not verify_password("wrong-password", hashed)


@pytest.mark.unit
def test_hash_is_salted():
    assert hash_password("Passw0rd!2025") != hash_password("Passw0rd!2025")


@pytest.mark.unit
def test_verify_invalid_hash_returns_false():
    assert not verify_password("any", "not-a-bcrypt-hash")
    assert not verify_password("any", "")


# --------------------------------------------------------------------------- #
#  JWT
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_token_roundtrip():
    token, expires_in = create_access_token(7, "alice", "editor")
    payload = decode_access_token(token)

    assert payload["sub"] == "7"
    assert payload["username"] == "alice"
    assert payload["role"] == "editor"
    assert expires_in == 480 * 60


@pytest.mark.unit
def test_token_custom_expiry():
    _, expires_in = create_access_token(1, "bob", "viewer", expires_minutes=30)
    assert expires_in == 30 * 60


@pytest.mark.unit
def test_tampered_token_invalid():
    token, _ = create_access_token(1, "alice", "viewer")
    tampered = token[:-6] + ("AAAAAA" if not token.endswith("AAAAAA") else "BBBBBB")

    with pytest.raises(BizError) as exc:
        decode_access_token(tampered)
    assert exc.value.code == ErrorCode.TOKEN_INVALID


@pytest.mark.unit
def test_expired_token():
    token, _ = create_access_token(1, "alice", "viewer", expires_minutes=-1)

    with pytest.raises(BizError) as exc:
        decode_access_token(token)
    assert exc.value.code == ErrorCode.TOKEN_EXPIRED


@pytest.mark.unit
def test_garbage_token_invalid():
    with pytest.raises(BizError) as exc:
        decode_access_token("not.a.token")
    assert exc.value.code == ErrorCode.TOKEN_INVALID


# --------------------------------------------------------------------------- #
#  注册校验
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize("username", ["abcd", "user_01", "A" * 50])
def test_validate_username_valid(username):
    validate_username(username)  # 不抛异常


@pytest.mark.unit
@pytest.mark.parametrize("username", ["abc", "ab-cd", "ab cd", "", "a" * 51, "用户123"])
def test_validate_username_invalid(username):
    with pytest.raises(BizError) as exc:
        validate_username(username)
    assert exc.value.code == ErrorCode.PARAM_INVALID


@pytest.mark.unit
@pytest.mark.parametrize("password", ["passw0rd", "A1234567", "abc12345xyz"])
def test_validate_password_valid(password):
    validate_password(password)


@pytest.mark.unit
@pytest.mark.parametrize("password", ["abcdefgh", "12345678", "ab12", "a1", "abc12345" * 5])
def test_validate_password_invalid(password):
    with pytest.raises(BizError) as exc:
        validate_password(password)
    assert exc.value.code == ErrorCode.PARAM_INVALID
