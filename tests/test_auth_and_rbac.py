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
        self.assertTrue(_is_public_path("/api/auth/login"))
        self.assertFalse(_is_public_path("/api/auth/me"))
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

    def test_mock_mode_does_not_grant_anonymous_admin_access(self):
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient

        from app.middleware.auth import JWTAuthMiddleware, create_access_token
        from app.security.session_identity import auth_fingerprint

        app = FastAPI()
        app.add_middleware(JWTAuthMiddleware)

        @app.get("/api/private")
        async def private(request: Request):
            return request.state.user

        current_user = {
            "id": 7,
            "username": "customer-7",
            "password_hash": "hash-v1",
            "user_type": "CUSTOMER",
            "employee_role": None,
            "status": "正常",
        }
        with patch(
            "app.middleware.auth._load_current_identity",
            new=AsyncMock(return_value=current_user),
        ), TestClient(app) as client:
            self.assertEqual(401, client.get("/api/private").status_code)
            self.assertEqual(
                401,
                client.get(
                    "/api/private",
                    headers={"Authorization": "Bearer invalid-token"},
                ).status_code,
            )
            token = create_access_token(
                {
                    "sub": 7,
                    "username": "customer-7",
                    "role": "客户",
                    "av": auth_fingerprint(current_user),
                }
            )
            response = client.get(
                "/api/private",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(7, response.json()["user_id"])
        self.assertEqual("客户", response.json()["role"])


class LoginEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_account_cannot_login(self):
        from app.api.auth import LoginRequest, login
        from app.security.passwords import hash_password

        row = {
            "id": 7,
            "username": "disabled-user",
            "password_hash": hash_password("Demo@123"),
            "user_type": "CUSTOMER",
            "employee_role": None,
            "real_name": "停用客户",
            "status": "停用",
        }
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(
            mappings=lambda: SimpleNamespace(first=lambda: row)
        )

        result = await login(
            LoginRequest(username="disabled-user", password="Demo@123"), db
        )

        self.assertEqual(403, result["code"])

    async def test_employee_requires_a_valid_employee_role(self):
        from app.api.auth import LoginRequest, login
        from app.security.passwords import hash_password

        row = {
            "id": 8,
            "username": "broken-employee",
            "password_hash": hash_password("Demo@123"),
            "user_type": "EMPLOYEE",
            "employee_role": None,
            "real_name": "异常员工",
            "status": "正常",
        }
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(
            mappings=lambda: SimpleNamespace(first=lambda: row)
        )

        result = await login(
            LoginRequest(username="broken-employee", password="Demo@123"), db
        )

        self.assertEqual(403, result["code"])


class RegisterEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_forces_customer_without_employee_role(self):
        from app.api.auth import RegisterRequest, register

        db = AsyncMock()
        db.execute.side_effect = [
            SimpleNamespace(first=lambda: None),
            SimpleNamespace(lastrowid=42),
        ]

        result = await register(
            RegisterRequest(
                username="new_customer",
                password="StrongPass@123",
                real_name="新客户",
                phone="13800138000",
            ),
            db,
        )

        _, params = db.execute.await_args_list[1].args
        self.assertEqual("new_customer", params["username"])
        self.assertNotIn("employee_role", params)
        self.assertEqual("客户", result["data"]["role"])


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


class UnifiedChatEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_stream_explicit_customer_id_overrides_stale_selected_target(self):
        from app.api.unified_chat import get_stream_subject_customer_id
        from app.model.route_decision import (
            RouteDecision,
            RouteDomain,
            RouteTask,
        )

        decision = RouteDecision(
            request_text="给客户ID是1的客户推荐产品",
            task=RouteTask.RECOMMEND,
            domain=RouteDomain.PRODUCT,
            intent="investment_recommendation",
            target_agent="advisor",
            confidence=0.95,
            entities={"customer_id": 1},
        )

        subject = get_stream_subject_customer_id(
            {"user_id": 120, "role": "管理员"},
            120,
            decision,
        )

        self.assertEqual(1, subject)

    async def test_unified_chat_uses_authenticated_identity_over_claimed_body_identity(self):
        from app.api.unified_chat import unified_chat
        from app.model.schemas import UnifiedChatRequest

        request = UnifiedChatRequest(
            message="查询我的账户信息",
            session_id="scope-test",
            user_id=999,
            user_role="管理员",
        )
        routed = SimpleNamespace(
            intent="business_operation",
            agent="operator",
            confidence=0.99,
            session_id="scope-test",
            reply="已识别账户服务请求",
            data=None,
            model_dump=lambda: {
                "intent": "business_operation",
                "agent": "operator",
                "confidence": 0.99,
                "session_id": "scope-test",
                "reply": "已识别账户服务请求",
                "data": None,
            },
        )
        router_agent = SimpleNamespace(route=AsyncMock(return_value=routed))

        memory_service = SimpleNamespace(archive_turn=AsyncMock())
        persistence = SimpleNamespace(persist_turn=AsyncMock())
        with patch("app.api.unified_chat.RouterAgent", return_value=router_agent), \
             patch("app.api.unified_chat.resolve_owned_session_id", new=AsyncMock(return_value="scope-test")), \
             patch("app.api.unified_chat.MemoryService", return_value=memory_service), \
             patch("app.api.unified_chat.PlatformPersistenceService", return_value=persistence):
            await unified_chat(
                request,
                AsyncMock(),
                {"user_id": 7, "role": "客户"},
            )

        router_agent.route.assert_awaited_once()
        route_kwargs = router_agent.route.await_args.kwargs
        self.assertEqual("查询我的账户信息", route_kwargs["message"])
        self.assertEqual("scope-test", route_kwargs["session_id"])
        self.assertEqual(7, route_kwargs["user_id"])
        self.assertEqual("客户", route_kwargs["user_role"])
        memory_service.archive_turn.assert_awaited_once_with(
            "scope-test", 7, "operator", request.message, routed.reply
        )

    def test_customer_subject_is_always_the_authenticated_customer(self):
        from app.api.unified_chat import get_subject_customer_id

        self.assertEqual(
            7,
            get_subject_customer_id(
                {"user_id": 7, "role": "客户"}, claimed_user_id=999
            ),
        )
        self.assertEqual(
            999,
            get_subject_customer_id(
                {"user_id": 20, "role": "理财顾问"}, claimed_user_id=999
            ),
        )


if __name__ == "__main__":
    unittest.main()
