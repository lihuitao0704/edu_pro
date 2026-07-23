import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class PasswordTests(unittest.TestCase):
    def test_hash_round_trip_and_wrong_password(self):
        from app.security.passwords import hash_password, verify_password

        encoded = hash_password("Demo@123")

        self.assertTrue(encoded.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("Demo@123", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))


class AuthorizationTests(unittest.TestCase):
    def test_authentication_is_secure_by_default_without_env_file(self):
        from app.config.settings import JWTSettings
        from pydantic import ValidationError

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValidationError):
                JWTSettings(_env_file=None)
            settings = JWTSettings(
                _env_file=None,
                JWT_SECRET_KEY="x" * 48,
            )

        self.assertFalse(settings.mock_mode)
        self.assertGreaterEqual(len(settings.secret_key), 48)

        with self.assertRaises(ValueError):
            JWTSettings(
                _env_file=None,
                JWT_SECRET_KEY="too-short",
                AUTH_MOCK_MODE=False,
            ).ensure_runtime_safe()

    def test_customer_scope_blocks_cross_customer_access(self):
        from fastapi import HTTPException

        from app.security.authorization import enforce_customer_scope

        with self.assertRaises(HTTPException) as raised:
            enforce_customer_scope({"user_id": 7, "role": "客户"}, 8)

        self.assertEqual(403, raised.exception.status_code)
        self.assertEqual(
            8,
            enforce_customer_scope({"user_id": 7, "role": "理财顾问"}, 8),
        )

    def test_authenticated_actor_id_ignores_spoofed_body_value(self):
        from app.security.authorization import authenticated_actor_id

        self.assertEqual(
            7,
            authenticated_actor_id({"user_id": 7, "role": "理财顾问"}, 999),
        )

    def test_frontend_shell_and_assets_are_public_but_apis_are_not(self):
        from app.middleware.auth import _is_public_path

        self.assertTrue(_is_public_path("/"))
        self.assertTrue(_is_public_path("/assets/app.js"))
        self.assertTrue(_is_public_path("/advisor"))
        self.assertFalse(_is_public_path("/api/customers"))

    def test_request_role_comes_from_authenticated_user(self):
        from app.security.authorization import get_request_role

        request = SimpleNamespace(
            state=SimpleNamespace(user={"user_id": 7, "role": "客户经理"})
        )

        self.assertEqual("客户经理", get_request_role(request))

    def test_missing_role_is_not_treated_as_admin(self):
        from app.security.authorization import get_request_role

        request = SimpleNamespace(state=SimpleNamespace(user={"user_id": 7}))

        self.assertEqual("", get_request_role(request))


class OperatorEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_ignores_claimed_role_and_uses_authenticated_role(self):
        from app.api.chat import OperatorChatRequest, chat_operator

        request = SimpleNamespace(
            state=SimpleNamespace(
                user={"user_id": 9, "role": "客户经理", "username": "manager"}
            )
        )
        body = OperatorChatRequest(
            message="创建客户工单",
            session_id="rbac-test",
            user_id=999,
            user_role="管理员",
        )
        expected = {
            "reply": "ok",
            "action": None,
            "params": {},
            "status": "ok",
            "session_id": "rbac-test",
        }

        with patch(
            "app.api.chat.operator_chat",
            new=AsyncMock(return_value=expected),
        ) as mocked:
            await chat_operator(body, request)

        mocked.assert_awaited_once_with(
            message=body.message,
            session_id=body.session_id,
            user_id=9,
            user_role="客户经理",
        )


if __name__ == "__main__":
    unittest.main()
