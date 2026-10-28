"""Demo access codes: code format, status rules, the sign-in route and the admin routes."""

import asyncio
import json
import os
import re
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from blueprints import auth_demo
from blueprints.admin import demo_codes as admin_demo_codes
from services import auth_limits
from services.demo_access import (
    DemoCodeSummary,
    DemoSignIn,
    IssuedDemoCode,
    demo_code_digest,
    demo_code_status,
    generate_demo_code,
)
from tests.helpers.request_helpers import build_request

_NOW = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)


def _row(**overrides):
    values = {
        "user_id": None,
        "first_used_at": None,
        "expires_at": None,
        "revoked_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _summary(**overrides):
    values = {
        "id": 7,
        "label": "株式会社サンプル",
        "status": "unused",
        "created_at": _NOW,
        "first_used_at": None,
        "expires_at": None,
        "used_nano_usd": None,
    }
    values.update(overrides)
    return DemoCodeSummary(**values)


def _body(response):
    return json.loads(response.body.decode())


class DemoCodeFormatTests(unittest.TestCase):
    def test_generated_code_has_the_readable_shape(self):
        code = generate_demo_code()
        self.assertRegex(code, r"^demo-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}$")
        self.assertIsNone(re.search(r"[ilo01]", code.removeprefix("demo-")))

    def test_digest_ignores_case_spaces_and_hyphens(self):
        digest = demo_code_digest("demo-ab3k-x9qa-7mpz")
        self.assertEqual(demo_code_digest("DEMO AB3K X9QA 7MPZ"), digest)
        self.assertEqual(demo_code_digest(" demoab3kx9qa7mpz "), digest)
        self.assertNotEqual(demo_code_digest("demo-ab3k-x9qa-7mpy"), digest)


class DemoCodeStatusTests(unittest.TestCase):
    def test_unused_until_first_use(self):
        self.assertEqual(demo_code_status(_row(), _NOW), "unused")

    def test_active_while_the_period_runs(self):
        row = _row(user_id=3, first_used_at=_NOW, expires_at=_NOW + timedelta(days=30))
        self.assertEqual(demo_code_status(row, _NOW + timedelta(days=29)), "active")

    def test_ended_on_expiry_even_before_the_purge_deletes_the_user(self):
        row = _row(user_id=3, first_used_at=_NOW, expires_at=_NOW + timedelta(days=30))
        self.assertEqual(demo_code_status(row, _NOW + timedelta(days=30)), "ended")

    def test_ended_when_the_recipient_deleted_the_account(self):
        # 同じコードで作り直すと利用枠が戻るので、再利用させない。
        # Recreating from the same code would restore the allowance, so it stays ended.
        row = _row(user_id=None, first_used_at=_NOW, expires_at=_NOW + timedelta(days=30))
        self.assertEqual(demo_code_status(row, _NOW + timedelta(days=1)), "ended")

    def test_revoked_wins_over_every_other_state(self):
        row = _row(user_id=3, first_used_at=_NOW, expires_at=_NOW + timedelta(days=30), revoked_at=_NOW)
        self.assertEqual(demo_code_status(row, _NOW), "revoked")


class DemoLoginRouteTests(unittest.TestCase):
    def _post(self, body, *, session=None):
        return build_request(method="POST", path="/api/auth/demo-login", json_body=body, session=session)

    def test_valid_code_signs_in_as_the_demo_user(self):
        request = self._post({"code": "demo-ab3k-x9qa-7mpz"})
        request.scope["session_id"] = "previous-session"
        sign_in = DemoSignIn(user_id=42, email="demo-7@demo.invalid", expires_at=_NOW + timedelta(days=30))
        with (
            patch.object(auth_demo, "consume_demo_login_limit", return_value=(True, None)),
            patch.object(auth_demo, "redeem_demo_code", AsyncMock(return_value=sign_in)) as redeem,
        ):
            response = asyncio.run(auth_demo.api_demo_login(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_body(response), {"status": "success", "expires_at": "2026-11-27T03:00:00+00:00"})
        redeem.assert_awaited_once_with("demo-ab3k-x9qa-7mpz")
        self.assertEqual(request.session["user_id"], 42)
        self.assertEqual(request.session["user_email"], "demo-7@demo.invalid")
        # セッション固定化を防ぐため、ログイン前の ID は破棄される。
        # The pre-login session ID is discarded to prevent session fixation.
        self.assertIsNone(request.scope["session_id"])

    def test_unusable_code_gets_one_message_whatever_the_reason(self):
        request = self._post({"code": "demo-wrong"})
        with (
            patch.object(auth_demo, "consume_demo_login_limit", return_value=(True, None)),
            patch.object(auth_demo, "redeem_demo_code", AsyncMock(return_value=None)),
        ):
            response = asyncio.run(auth_demo.api_demo_login(request))

        self.assertEqual(response.status_code, 401)
        self.assertIn("コードが正しくないか", _body(response)["error"])
        self.assertNotIn("user_id", request.session)

    def test_rate_limit_stops_before_the_code_is_looked_up(self):
        request = self._post({"code": "demo-ab3k-x9qa-7mpz"})
        redeem = AsyncMock()
        with (
            patch.object(
                auth_demo,
                "consume_demo_login_limit",
                return_value=(False, "デモコードの入力回数が多すぎます。120秒ほど待ってから再試行してください。"),
            ),
            patch.object(auth_demo, "redeem_demo_code", redeem),
        ):
            response = asyncio.run(auth_demo.api_demo_login(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "120")
        redeem.assert_not_awaited()

    def test_missing_code_is_rejected_without_a_lookup(self):
        request = self._post({"code": ""})
        redeem = AsyncMock()
        with patch.object(auth_demo, "redeem_demo_code", redeem):
            response = asyncio.run(auth_demo.api_demo_login(request))
        self.assertEqual(response.status_code, 400)
        redeem.assert_not_awaited()


class DemoLoginRateLimitTests(unittest.TestCase):
    def setUp(self):
        auth_limits.clear_in_memory_rate_limit_state()
        self.addCleanup(auth_limits.clear_in_memory_rate_limit_state)

    def test_entries_from_one_address_are_capped(self):
        request = build_request(method="POST", path="/api/auth/demo-login")
        with (
            patch.dict(os.environ, {"DEMO_LOGIN_PER_IP_LIMIT": "2"}),
            patch("services.auth_limits.get_redis_client", return_value=None),
        ):
            results = [auth_limits.consume_demo_login_limit(request) for _ in range(3)]

        self.assertEqual(results[:2], [(True, None), (True, None)])
        allowed, message = results[2]
        self.assertFalse(allowed)
        self.assertIn("デモコードの入力回数が多すぎます", message)


class AdminDemoCodeRouteTests(unittest.TestCase):
    def test_every_route_requires_an_admin_session(self):
        calls = (
            lambda request: admin_demo_codes.api_list_demo_codes(request),
            lambda request: admin_demo_codes.api_issue_demo_code(request),
            lambda request: admin_demo_codes.api_revoke_demo_code(request, 1),
        )
        for call in calls:
            with self.subTest(call=call):
                request = build_request(method="POST", json_body={"label": "x"}, session={})
                response = asyncio.run(call(request))
                self.assertEqual(response.status_code, 401)

    def test_issue_returns_the_code_once_with_the_listing_fields(self):
        request = build_request(method="POST", json_body={"label": "  株式会社サンプル "}, session={"is_admin": True})
        issued = IssuedDemoCode(code="demo-ab3k-x9qa-7mpz", summary=_summary())
        with patch.object(admin_demo_codes, "issue_demo_code", AsyncMock(return_value=issued)) as issue:
            response = asyncio.run(admin_demo_codes.api_issue_demo_code(request))

        self.assertEqual(response.status_code, 201)
        payload = _body(response)
        self.assertEqual(payload["code"], "demo-ab3k-x9qa-7mpz")
        self.assertEqual(payload["item"]["label"], "株式会社サンプル")
        self.assertEqual(payload["item"]["status"], "unused")
        self.assertEqual(payload["item"]["limit_usd"], 1.5)
        self.assertIsNone(payload["item"]["used_usd"])
        issue.assert_awaited_once_with("株式会社サンプル")

    def test_issue_rejects_an_empty_label(self):
        request = build_request(method="POST", json_body={"label": "   "}, session={"is_admin": True})
        issue = AsyncMock()
        with patch.object(admin_demo_codes, "issue_demo_code", issue):
            response = asyncio.run(admin_demo_codes.api_issue_demo_code(request))
        self.assertEqual(response.status_code, 400)
        issue.assert_not_awaited()

    def test_list_reports_spend_in_dollars_for_active_codes(self):
        request = build_request(session={"is_admin": True})
        active = _summary(
            status="active",
            first_used_at=_NOW,
            expires_at=_NOW + timedelta(days=30),
            used_nano_usd=120_000_000,
        )
        with patch.object(admin_demo_codes, "list_demo_codes", AsyncMock(return_value=[active, _summary(id=6)])):
            response = asyncio.run(admin_demo_codes.api_list_demo_codes(request))

        codes = _body(response)["codes"]
        self.assertEqual([code["id"] for code in codes], [7, 6])
        self.assertEqual(codes[0]["used_usd"], 0.12)
        self.assertEqual(codes[0]["expires_at"], "2026-11-27T03:00:00+00:00")
        self.assertNotIn("code", codes[0])

    def test_revoke_reports_a_missing_code(self):
        request = build_request(method="POST", session={"is_admin": True})
        with patch.object(admin_demo_codes, "revoke_demo_code", AsyncMock(return_value=None)):
            response = asyncio.run(admin_demo_codes.api_revoke_demo_code(request, 99))
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
