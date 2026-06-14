import unittest

from services.attached_files import PreparedAttachedFile
from services.repositories.chat_repository import ChatRepository


# チャット履歴の分岐操作(ブランチング)のSQL挙動をメモリ上でシミュレートするための最小限のインメモリ疑似カーソルクラス。
# Minimal in-memory emulation cursor class to mock SQL queries issued by chat branching methods.
class FakeCursor:
    """Minimal in-memory emulation of the SQL the branching methods issue."""

    def __init__(self, store):
        self.store = store
        self._result_one = None
        self._result_all = []
        self.rowcount = 0
        self.closed = False

    # クエリを実行し、インメモリのストア内のデータを更新・抽出します。
    # Execute a query, modifying or fetching from the in-memory data store.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        params = params or ()
        self._result_one = None
        self._result_all = []
        self.rowcount = 0

        # メッセージの新規追加(インサート)処理をシミュレート
        # Simulate inserting a new chat message
        if normalized.startswith("INSERT INTO chat_history"):
            (
                chat_room_id,
                message,
                sender,
                file_names_json,
                parent_id,
                message_parts_json,
                attached_file_contents_json,
            ) = params
            new_id = self.store["seq"]
            self.store["seq"] += 1
            self.store["history"].append(
                {
                    "id": new_id,
                    "chat_room_id": chat_room_id,
                    "message": message,
                    "sender": sender,
                    "parent_id": parent_id,
                    "active_child_id": None,
                    "timestamp": None,
                    "attached_file_names": file_names_json,
                    "message_parts": message_parts_json,
                    "attached_file_contents": attached_file_contents_json,
                }
            )
            self._result_one = (new_id,)
            return

        # ルームのアクティブルート更新をシミュレート
        # Simulate updating the active root message of a room
        if normalized.startswith("UPDATE chat_rooms SET active_root_id"):
            active_root_id, room_id = params
            self.store["rooms"].setdefault(room_id, {})["active_root_id"] = active_root_id
            self.rowcount = 1
            return

        # ルームのタイトル変更をシミュレート
        # Simulate updating the chat room title
        if normalized.startswith("UPDATE chat_rooms SET title"):
            new_title, room_id, *allowed_titles = params
            room = self.store["rooms"].get(room_id)
            if room and room.get("title") in allowed_titles:
                room["title"] = new_title
                self.rowcount = 1
            return

        # メッセージのアクティブな子メッセージ(子ブランチ)IDの更新をシミュレート
        # Simulate updating the active child message ID of a parent message
        if normalized.startswith("UPDATE chat_history SET active_child_id"):
            active_child_id, target_id, room_id = params
            for row in self.store["history"]:
                if row["id"] == target_id and row["chat_room_id"] == room_id:
                    row["active_child_id"] = active_child_id
                    self.rowcount = 1
            return

        # ルームの全履歴(全世代・全分岐含む)の取得をシミュレート
        # Simulate fetching the entire chat history for a room
        if normalized.startswith("SELECT id, message, sender, parent_id, active_child_id"):
            (room_id,) = params
            rows = [r for r in self.store["history"] if r["chat_room_id"] == room_id]
            rows.sort(key=lambda r: r["id"])
            self._result_all = [
                (
                    r["id"],
                    r["message"],
                    r["sender"],
                    r["parent_id"],
                    r["active_child_id"],
                    r["timestamp"],
                    r["attached_file_names"],
                    r.get("message_parts"),
                    r.get("attached_file_contents"),
                )
                for r in rows
            ]
            return

        # アクティブルートIDの取得をシミュレート
        # Simulate retrieving the active root message ID
        if normalized.startswith("SELECT active_root_id FROM chat_rooms"):
            (room_id,) = params
            room = self.store["rooms"].get(room_id)
            self._result_one = (room.get("active_root_id"),) if room else None
            return

        # 親メッセージIDの取得をシミュレート
        # Simulate retrieving the parent message ID of a message
        if normalized.startswith("SELECT parent_id FROM chat_history"):
            target_id, room_id = params
            for row in self.store["history"]:
                if row["id"] == target_id and row["chat_room_id"] == room_id:
                    self._result_one = (row["parent_id"],)
                    return
            self._result_one = None
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    # クエリの実行結果から1レコード取得します。
    # Fetch a single query result.
    def fetchone(self):
        return self._result_one

    # クエリの実行結果から全レコードを取得します。
    # Fetch all query results.
    def fetchall(self):
        return self._result_all

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# テスト用の疑似DBコネクションクラス。
# Mock database connection class for testing.
class FakeConnection:
    def __init__(self, store):
        self.store = store

    # Prepare the object when entering the context.
    def __enter__(self):
        return self

    # Clean up when leaving the context.
    def __exit__(self, *exc):
        return False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self):
        return FakeCursor(self.store)

    # コミット処理（テスト用のためパス）
    # Commit transaction (no-op for mock)
    def commit(self):
        pass

    # ロールバック処理（テスト用のためパス）
    # Rollback transaction (no-op for mock)
    def rollback(self):
        pass


# チャットの会話履歴における分岐、メッセージの編集、再生成、アクティブパスの切り替えを検証するテストクラス。
# Test class to verify branching, editing messages, regenerating, and switching active paths in chat history.
class ChatBranchingTestCase(unittest.TestCase):
    # テストケースの実行前にインメモリのデータストアとリポジトリインスタンスを初期化します。
    # Initialize the in-memory store and the ChatRepository instance before each test.
    def setUp(self):
        self.store = {
            "seq": 1,
            "history": [],
            "rooms": {"room-1": {"active_root_id": None, "title": "新規チャット"}},
        }
        self.repo = ChatRepository(
            connection_getter=lambda: FakeConnection(self.store),
            retryable_error_checker=lambda exc: False,
            rollback=lambda conn: True,
            sleep=lambda s: None,
        )

    # 指定されたメッセージ、送信者、親メッセージIDを使用して、チャット履歴にメッセージを保存します。
    # Save a message to the chat history with the given content, sender, and parent message ID.
    def _save(self, message, sender, parent_id=None):
        return self.repo.save_message("room-1", message, sender, None, parent_id)

    # パス情報ノードのリストからメッセージ本文と送信者のペアのリストを抽出して返します。
    # Extract and return a list of (message, sender) tuples from the list of path nodes.
    def _texts(self, path):
        return [(node["message"], node["sender"]) for node in path]

    # 分岐のない一本道の会話履歴において、バージョン数が1となりインデックスも1であることを検証します。
    # Verify that a linear conversation without branching has version_count=1 and version_index=1 for all nodes.
    def test_linear_conversation_has_single_versions(self):
        u1 = self._save("hi", "user")
        self._save("hello", "assistant", u1)

        path = self.repo.get_active_path("room-1")
        self.assertEqual(self._texts(path), [("hi", "user"), ("hello", "assistant")])
        for node in path:
            self.assertEqual(node["version_count"], 1)
            self.assertEqual(node["version_index"], 1)

    # チャットルームのタイトル変更処理で、現在のタイトルが対象リストに含まれている場合のみ変更されることを検証します。
    # Verify that the chat room title is only renamed if the current title is matched in the allowed titles list.
    def test_conditional_room_rename_preserves_manual_title(self):
        updated = self.repo.rename_room_if_current_title_in(
            "room-1",
            "AIタイトル",
            ["新規チャット"],
        )
        self.assertTrue(updated)
        self.assertEqual(self.store["rooms"]["room-1"]["title"], "AIタイトル")

        updated_again = self.repo.rename_room_if_current_title_in(
            "room-1",
            "別タイトル",
            ["新規チャット"],
        )
        self.assertFalse(updated_again)
        self.assertEqual(self.store["rooms"]["room-1"]["title"], "AIタイトル")

    # アシスタントメッセージの再生成により並列（シブリング）な回答バージョンが作成され、アクティブブランチを切り替えられることを検証します。
    # Verify that regenerating assistant responses creates sibling versions and allows switching between them.
    def test_regenerate_creates_switchable_assistant_versions(self):
        u1 = self._save("hi", "user")
        a1 = self._save("answer one", "assistant", u1)
        # 再生成：同じユーザーメッセージの下にアシスタントメッセージの兄弟を追加
        # Regeneration: a sibling assistant under the same user message.
        a2 = self._save("answer two", "assistant", u1)

        path = self.repo.get_active_path("room-1")
        # アクティブなブランチの末尾は最新の回答になる
        # Active branch now ends with the newest answer.
        self.assertEqual(self._texts(path), [("hi", "user"), ("answer two", "assistant")])
        answer = path[-1]
        self.assertEqual(answer["version_count"], 2)
        self.assertEqual(answer["version_index"], 2)
        self.assertEqual(answer["sibling_ids"], [a1, a2])

        # 最初の回答にブランチを切り替える
        # Switch back to the first answer.
        switched = self.repo.switch_branch("room-1", a1)
        self.assertEqual(self._texts(switched), [("hi", "user"), ("answer one", "assistant")])
        self.assertEqual(switched[-1]["version_index"], 1)

    # 過去のユーザーメッセージの編集によってブランチが分岐し、以前の会話ブランチに戻る（切り替える）ことができることを検証します。
    # Verify that editing an earlier user message forks a new branch, and the user can switch back to the original branch.
    def test_edit_user_message_forks_branch_and_preserves_original(self):
        u1 = self._save("first question", "user")
        self._save("first answer", "assistant", u1)
        # 最初のユーザーメッセージの編集により、新しいルートの兄弟ブランチに分岐
        # Editing the first user message forks a sibling root.
        u2 = self._save("edited question", "user")
        self._save("edited answer", "assistant", u2)

        path = self.repo.get_active_path("room-1")
        self.assertEqual(
            self._texts(path),
            [("edited question", "user"), ("edited answer", "assistant")],
        )
        user_node = path[0]
        self.assertEqual(user_node["version_count"], 2)
        self.assertEqual(user_node["version_index"], 2)
        self.assertEqual(user_node["sibling_ids"], [u1, u2])

        # 切り替えによって元の質問と回答が復元される
        # Switching back restores the original question and its answer.
        switched = self.repo.switch_branch("room-1", u1)
        self.assertEqual(
            self._texts(switched),
            [("first question", "user"), ("first answer", "assistant")],
        )

    # アクティブな末端（リーフ）メッセージIDが、再生成やブランチの切り替えに追従して正しく更新されることを検証します。
    # Verify that the active leaf ID correctly tracks the tip of the active branch during regeneration or switching.
    def test_active_leaf_tracks_branch_tip(self):
        u1 = self._save("hi", "user")
        a1 = self._save("answer one", "assistant", u1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a1)

        a2 = self._save("answer two", "assistant", u1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a2)

        self.repo.switch_branch("room-1", a1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a1)

    # LLMに渡すコンテキストメッセージ一覧が、現在のアクティブなブランチに沿ったものであることを検証します。
    # Verify that the message history formatted for LLM follows the currently active branch.
    def test_llm_context_follows_active_branch(self):
        u1 = self._save("hi", "user")
        self._save("answer one", "assistant", u1)
        self._save("answer two", "assistant", u1)

        messages = self.repo.get_room_messages_for_llm("room-1")
        self.assertEqual(
            messages,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "answer two"},
            ],
        )

    # 添付ファイルのコンテンツが、明示的に取得フラグを指定した場合のみ読み込まれ、通常は除外されることを検証します。
    # Verify that attached file contents are only loaded when explicitly requested, otherwise excluded from the path metadata.
    def test_attachment_contents_are_internal_to_explicit_active_path_load(self):
        self.repo.save_message(
            "room-1",
            "summarize this",
            "user",
            ["sample.pdf"],
            None,
            None,
            [PreparedAttachedFile(name="sample.pdf", content="[page 1]\nHello PDF")],
        )

        public_path = self.repo.get_active_path("room-1")
        self.assertEqual(public_path[0]["attached_file_names"], ["sample.pdf"])
        self.assertNotIn("attached_file_contents", public_path[0])

        internal_path = self.repo.get_active_path("room-1", include_attachment_contents=True)
        self.assertEqual(
            internal_path[0]["attached_file_contents"],
            [{"name": "sample.pdf", "content": "[page 1]\nHello PDF"}],
        )


if __name__ == "__main__":
    unittest.main()
