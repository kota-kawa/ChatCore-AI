import unittest

from services.repositories.chat_repository import ChatRepository


class FakeCursor:
    """Minimal in-memory emulation of the SQL the branching methods issue."""

    def __init__(self, store):
        self.store = store
        self._result_one = None
        self._result_all = []
        self.rowcount = 0
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        params = params or ()
        self._result_one = None
        self._result_all = []
        self.rowcount = 0

        if normalized.startswith("INSERT INTO chat_history"):
            chat_room_id, message, sender, file_names_json, parent_id = params
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
                }
            )
            self._result_one = (new_id,)
            return

        if normalized.startswith("UPDATE chat_rooms SET active_root_id"):
            active_root_id, room_id = params
            self.store["rooms"].setdefault(room_id, {})["active_root_id"] = active_root_id
            self.rowcount = 1
            return

        if normalized.startswith("UPDATE chat_rooms SET title"):
            new_title, room_id, *allowed_titles = params
            room = self.store["rooms"].get(room_id)
            if room and room.get("title") in allowed_titles:
                room["title"] = new_title
                self.rowcount = 1
            return

        if normalized.startswith("UPDATE chat_history SET active_child_id"):
            active_child_id, target_id, room_id = params
            for row in self.store["history"]:
                if row["id"] == target_id and row["chat_room_id"] == room_id:
                    row["active_child_id"] = active_child_id
                    self.rowcount = 1
            return

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
                )
                for r in rows
            ]
            return

        if normalized.startswith("SELECT active_root_id FROM chat_rooms"):
            (room_id,) = params
            room = self.store["rooms"].get(room_id)
            self._result_one = (room.get("active_root_id"),) if room else None
            return

        if normalized.startswith("SELECT parent_id FROM chat_history"):
            target_id, room_id = params
            for row in self.store["history"]:
                if row["id"] == target_id and row["chat_room_id"] == room_id:
                    self._result_one = (row["parent_id"],)
                    return
            self._result_one = None
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self._result_one

    def fetchall(self):
        return self._result_all

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


class ChatBranchingTestCase(unittest.TestCase):
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

    def _save(self, message, sender, parent_id=None):
        return self.repo.save_message("room-1", message, sender, None, parent_id)

    def _texts(self, path):
        return [(node["message"], node["sender"]) for node in path]

    def test_linear_conversation_has_single_versions(self):
        u1 = self._save("hi", "user")
        self._save("hello", "assistant", u1)

        path = self.repo.get_active_path("room-1")
        self.assertEqual(self._texts(path), [("hi", "user"), ("hello", "assistant")])
        for node in path:
            self.assertEqual(node["version_count"], 1)
            self.assertEqual(node["version_index"], 1)

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

    def test_regenerate_creates_switchable_assistant_versions(self):
        u1 = self._save("hi", "user")
        a1 = self._save("answer one", "assistant", u1)
        # Regeneration: a sibling assistant under the same user message.
        a2 = self._save("answer two", "assistant", u1)

        path = self.repo.get_active_path("room-1")
        # Active branch now ends with the newest answer.
        self.assertEqual(self._texts(path), [("hi", "user"), ("answer two", "assistant")])
        answer = path[-1]
        self.assertEqual(answer["version_count"], 2)
        self.assertEqual(answer["version_index"], 2)
        self.assertEqual(answer["sibling_ids"], [a1, a2])

        # Switch back to the first answer.
        switched = self.repo.switch_branch("room-1", a1)
        self.assertEqual(self._texts(switched), [("hi", "user"), ("answer one", "assistant")])
        self.assertEqual(switched[-1]["version_index"], 1)

    def test_edit_user_message_forks_branch_and_preserves_original(self):
        u1 = self._save("first question", "user")
        self._save("first answer", "assistant", u1)
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

        # Switching back restores the original question and its answer.
        switched = self.repo.switch_branch("room-1", u1)
        self.assertEqual(
            self._texts(switched),
            [("first question", "user"), ("first answer", "assistant")],
        )

    def test_active_leaf_tracks_branch_tip(self):
        u1 = self._save("hi", "user")
        a1 = self._save("answer one", "assistant", u1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a1)

        a2 = self._save("answer two", "assistant", u1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a2)

        self.repo.switch_branch("room-1", a1)
        self.assertEqual(self.repo.get_active_leaf_id("room-1"), a1)

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


if __name__ == "__main__":
    unittest.main()
