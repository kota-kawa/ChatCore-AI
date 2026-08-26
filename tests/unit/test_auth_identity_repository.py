import unittest
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql

from services.models import User
from services.repositories.auth_identity_repository import AuthIdentityRepository
from services.repositories.user_repository import UserRepository


class AuthIdentityRepositoryContractTestCase(unittest.IsolatedAsyncioTestCase):
    def make_session(self):
        session = Mock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        session.scalar = AsyncMock()
        return session

    @staticmethod
    def compiled_sql(statement) -> str:
        return str(statement.compile(dialect=postgresql.dialect()))

    async def test_google_user_creation_keeps_provider_fields_out_of_users(self):
        session = self.make_session()

        def assign_user_id() -> None:
            session.add.call_args.args[0].id = 41

        session.flush.side_effect = assign_user_id
        repository = AuthIdentityRepository(session)

        user_id = await repository.create(
            email="google@example.com",
            username="Google User",
            avatar_url="/avatar.png",
            auth_provider="google",
            provider_user_id="google-subject-123",
            provider_email="google@example.com",
            is_verified=True,
            preferred_locale="ja",
        )

        self.assertEqual(user_id, 41)
        created_user = session.add.call_args.args[0]
        self.assertIsInstance(created_user, User)
        self.assertFalse(hasattr(created_user, "auth_provider"))
        self.assertFalse(hasattr(created_user, "provider_user_id"))
        self.assertFalse(hasattr(created_user, "provider_email"))

        provider_statement = session.execute.await_args.args[0]
        sql = self.compiled_sql(provider_statement)
        self.assertIn("INSERT INTO user_auth_providers", sql)
        self.assertNotIn("UPDATE users", sql)

    async def test_email_user_creation_uses_the_same_provider_boundary(self):
        session = self.make_session()

        def assign_user_id() -> None:
            session.add.call_args.args[0].id = 42

        session.flush.side_effect = assign_user_id
        repository = AuthIdentityRepository(session)

        user_id = await repository.create(
            email="email@example.com",
            username="Email User",
            avatar_url="/avatar.png",
            auth_provider="email",
            provider_user_id="email@example.com",
            provider_email="email@example.com",
            is_verified=False,
            preferred_locale=None,
        )

        self.assertEqual(user_id, 42)
        provider_statement = session.execute.await_args.args[0]
        self.assertIn(
            "INSERT INTO user_auth_providers",
            self.compiled_sql(provider_statement),
        )

    async def test_link_google_account_only_upserts_provider_table(self):
        session = self.make_session()
        repository = AuthIdentityRepository(session)

        await repository.link_google_account(
            user_id=7,
            google_user_id="google-subject-456",
            provider_email="linked@example.com",
        )

        session.execute.assert_awaited_once()
        statement = session.execute.await_args.args[0]
        sql = self.compiled_sql(statement)
        self.assertIn("INSERT INTO user_auth_providers", sql)
        self.assertNotIn("UPDATE users", sql)

    def test_general_user_repository_has_no_authentication_writes(self):
        for method_name in (
            "create",
            "get_by_email",
            "get_by_google_id",
            "link_google_account",
            "set_verified",
        ):
            self.assertFalse(hasattr(UserRepository, method_name), method_name)


if __name__ == "__main__":
    unittest.main()
