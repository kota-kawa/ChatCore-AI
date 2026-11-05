"""メモの埋め込みベクトル保存（store_memo_embedding）が、期待するリビジョンで更新を絞り込むことを検証するテスト。

Tests that store_memo_embedding restricts its update to the expected memo revision.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.memo_embedding_service import store_memo_embedding


# session_scope の代役。with ブロックに渡されたセッションをそのまま返す。
# Stand-in for session_scope that yields the session it was given.
class _SessionScope:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


# 実行された UPDATE をコンパイルし、メモ ID と期待リビジョンが条件に入っていることを確かめる。
# Compiles the executed UPDATE and checks the memo id and expected revision are part of its conditions.
class MemoEmbeddingRevisionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_embedding_uses_native_async_revision_guard(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.begin = MagicMock(return_value=session)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.memo_embedding_service.session_scope",
            return_value=_SessionScope(session),
        ):
            await store_memo_embedding(9, [0.1, 0.2], expected_revision=4)

        statement = session.execute.await_args.args[0]
        compiled = statement.compile(dialect=dialect())
        self.assertIn("revision", str(compiled))
        self.assertIn(9, compiled.params.values())
        self.assertIn(4, compiled.params.values())


if __name__ == "__main__":
    unittest.main()
