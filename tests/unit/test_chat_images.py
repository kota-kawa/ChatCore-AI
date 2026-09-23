"""チャット画像の検証・保存・配信と、GPT-6 Luna への受け渡しを検証する。

Verifies chat image validation, private storage and delivery, and how images reach GPT-6 Luna
(and never reach text-only models).
"""

import asyncio
import base64
import io
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from starlette.responses import JSONResponse

from blueprints.chat.chat_image_media import get_chat_image, get_chat_image_thumbnail
from services import llm
from services.attached_files import AttachedFileValidationError
from services.chat_context import select_recent_messages
from services.chat_context_recovery import build_recovery_base_messages
from services.chat_image_storage import (
    CHAT_IMAGE_UPLOAD_ROOT_ENV,
    chat_image_belongs_to,
    chat_image_owner_key,
    cleanup_unreferenced_chat_images,
    resolve_chat_image_path,
)
from services.chat_images import (
    IMAGE_INPUTS_KEY,
    apply_attached_images_for_model,
    build_openai_image_parts,
    decode_chat_images_from_storage,
    estimate_image_input_tokens,
    prepare_chat_images,
    split_image_attachments,
)
from services.chat_use_case import ChatPostUseCase, _ChatPostTurn
from services.ephemeral_store import EphemeralChatStore
from services.llm_context_budget import estimate_messages_tokens
from services.repositories.chat_repository import ChatRepository

OWNER = "user:42"
OTHER_OWNER = "user:7"


def _image_base64(size=(64, 48), fmt="PNG", color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _animated_gif_base64():
    frames = [Image.new("RGB", (16, 16), color) for color in ((255, 0, 0), (0, 255, 0))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _UploadRootTestCase(unittest.TestCase):
    """Point the chat image storage at a throwaway directory for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch.dict(os.environ, {CHAT_IMAGE_UPLOAD_ROOT_ENV: self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _store(self, owner=OWNER, name="photo.png", size=(64, 48)):
        return prepare_chat_images([{"name": name, "data_base64": _image_base64(size)}], owner)[0]


class PrepareChatImagesTests(_UploadRootTestCase):
    def test_stores_a_webp_display_and_thumbnail_bound_to_the_owner(self):
        image = self._store()

        self.assertEqual((image.name, image.width, image.height), ("photo.png", 64, 48))
        for thumbnail in (False, True):
            with Image.open(resolve_chat_image_path(image.id, thumbnail=thumbnail)) as stored:
                self.assertEqual(stored.format, "WEBP")
        self.assertTrue(chat_image_belongs_to(image.id, OWNER))
        self.assertFalse(chat_image_belongs_to(image.id, OTHER_OWNER))

    def test_rejects_bytes_that_are_not_an_image_even_with_an_image_name(self):
        payload = {"name": "fake.png", "data_base64": base64.b64encode(b"not an image at all").decode()}
        with self.assertRaises(AttachedFileValidationError):
            prepare_chat_images([payload], OWNER)

    def test_rejects_animated_gifs(self):
        with self.assertRaises(AttachedFileValidationError):
            prepare_chat_images([{"name": "anim.gif", "data_base64": _animated_gif_base64()}], OWNER)

    def test_rejects_images_over_the_size_limit_before_decoding(self):
        oversized = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024)).decode()
        with self.assertRaises(AttachedFileValidationError):
            prepare_chat_images([{"name": "big.png", "data_base64": oversized}], OWNER)

    def test_requires_an_owner(self):
        with self.assertRaises(AttachedFileValidationError):
            prepare_chat_images([{"name": "photo.png", "data_base64": _image_base64()}], None)

    def test_splits_images_from_documents_by_extension(self):
        documents, images = split_image_attachments(
            [{"name": "notes.txt"}, {"name": "Photo.JPG"}, {"name": "report.pdf"}, {"name": "shot.webp"}]
        )
        self.assertEqual([item["name"] for item in documents], ["notes.txt", "report.pdf"])
        self.assertEqual([item["name"] for item in images], ["Photo.JPG", "shot.webp"])


class ChatImageStorageTests(_UploadRootTestCase):
    def test_owner_key_prefers_the_signed_in_user_over_the_guest_session(self):
        self.assertEqual(chat_image_owner_key(user_id=42, sid="abc"), "user:42")
        self.assertEqual(chat_image_owner_key(user_id=None, sid="abc"), "guest:abc")
        self.assertIsNone(chat_image_owner_key(user_id=None, sid=None))

    def test_path_resolution_rejects_anything_but_a_generated_id(self):
        for image_id in ("../etc/passwd", "abc", "g" * 48, ""):
            with self.subTest(image_id=image_id), self.assertRaises(ValueError):
                resolve_chat_image_path(image_id)

    def test_cleanup_removes_only_old_unreferenced_files(self):
        referenced = self._store()
        orphan = self._store()
        recent_orphan = self._store()
        old = time.time() - 7200
        for image in (referenced, orphan):
            for thumbnail in (False, True):
                os.utime(resolve_chat_image_path(image.id, thumbnail=thumbnail), (old, old))

        deleted = cleanup_unreferenced_chat_images({referenced.id}, grace_seconds=3600)

        self.assertEqual(deleted, 2)
        self.assertTrue(os.path.isfile(resolve_chat_image_path(referenced.id)))
        self.assertFalse(os.path.exists(resolve_chat_image_path(orphan.id)))
        self.assertTrue(os.path.isfile(resolve_chat_image_path(recent_orphan.id, thumbnail=True)))


class ChatImageMediaRouteTests(_UploadRootTestCase):
    def _request(self, **session):
        return SimpleNamespace(session=session)

    def test_owner_receives_the_image_and_thumbnail(self):
        image = self._store()
        for route in (get_chat_image, get_chat_image_thumbnail):
            with self.subTest(route=route.__name__):
                response = asyncio.run(route(self._request(user_id=42), image.id))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.media_type, "image/webp")
                self.assertTrue(response.headers["cache-control"].startswith("private"))

    def test_other_viewers_get_the_same_404_as_a_missing_image(self):
        image = self._store()
        for session in ({"user_id": 7}, {"sid": "guest-session"}, {}):
            with self.subTest(session=session):
                response = asyncio.run(get_chat_image(self._request(**session), image.id))
                self.assertEqual(response.status_code, 404)

    def test_guest_images_are_served_to_the_same_guest_session(self):
        image = self._store(owner="guest:guest-session")
        response = asyncio.run(get_chat_image(self._request(sid="guest-session"), image.id))
        self.assertEqual(response.status_code, 200)


class ModelInputTests(_UploadRootTestCase):
    def test_luna_receives_references_and_text_only_models_receive_a_note(self):
        image = self._store()
        messages = [{"role": "user", "content": "what is this?", "attached_images": [image.to_storage()]}]

        for_luna = apply_attached_images_for_model(messages, "gpt-6-luna")
        self.assertEqual(for_luna[0][IMAGE_INPUTS_KEY], [image.to_storage()])
        self.assertEqual(for_luna[0]["content"], "what is this?")
        self.assertNotIn("attached_images", for_luna[0])

        for_oss = apply_attached_images_for_model(messages, "openai/gpt-oss-120b")
        self.assertNotIn(IMAGE_INPUTS_KEY, for_oss[0])
        self.assertIn("photo.png", for_oss[0]["content"])
        self.assertTrue(for_oss[0]["content"].endswith("what is this?"))

    def test_image_parts_match_each_openai_endpoint(self):
        image = self._store()
        chat_part = build_openai_image_parts([image.to_storage()], responses_api=False)[0]
        responses_part = build_openai_image_parts([image.to_storage()], responses_api=True)[0]

        self.assertEqual(chat_part["type"], "image_url")
        self.assertTrue(chat_part["image_url"]["url"].startswith("data:image/webp;base64,"))
        self.assertEqual(chat_part["image_url"]["detail"], "auto")
        self.assertEqual(responses_part["type"], "input_image")
        self.assertTrue(responses_part["image_url"].startswith("data:image/webp;base64,"))
        self.assertEqual(responses_part["detail"], "auto")

    def test_images_missing_from_storage_are_skipped(self):
        image = self._store()
        os.remove(resolve_chat_image_path(image.id))
        self.assertEqual(build_openai_image_parts([image.to_storage()], responses_api=True), [])

    def test_invalid_stored_references_are_ignored(self):
        self.assertEqual(decode_chat_images_from_storage([{"id": "../x"}, "junk", None]), [])


class LlmRequestImageTests(_UploadRootTestCase):
    def _conversation(self, image):
        return [
            {"role": "system", "content": "base prompt"},
            {"role": "user", "content": "earlier", IMAGE_INPUTS_KEY: [image.to_storage()]},
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": "describe it", IMAGE_INPUTS_KEY: [image.to_storage()]},
        ]

    def test_luna_tool_turn_sends_image_url_parts_before_the_text(self):
        image = self._store()
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(__iter__=lambda _self: iter(()))
        tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
        with patch.object(llm, "openai_client", client):
            list(llm.get_llm_response_stream(self._conversation(image), llm.GPT_6_LUNA_MODEL, tools=tools))

        sent = client.chat.completions.create.call_args.kwargs["messages"]
        latest = sent[-1]
        self.assertEqual([part["type"] for part in latest["content"]], ["image_url", "text"])
        self.assertEqual(latest["content"][1]["text"], "describe it")
        self.assertTrue(all(IMAGE_INPUTS_KEY not in message for message in sent))

    def test_luna_responses_turn_sends_input_image_parts(self):
        image = self._store()
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(output_text="ok", usage=None)
        with patch.object(llm, "openai_client", client):
            llm.get_openai_response(self._conversation(image), llm.GPT_6_LUNA_MODEL)

        sent = client.responses.create.call_args.kwargs["input"]
        self.assertEqual([part["type"] for part in sent[-1]["content"]], ["input_image", "input_text"])

    def test_history_breakpoint_stays_on_the_text_after_the_images(self):
        image = self._store()
        messages = [
            {"role": "system", "content": "base prompt"},
            {"role": "user", "content": "earlier", IMAGE_INPUTS_KEY: [image.to_storage()]},
            {"role": "system", "content": "<runtime_context>now</runtime_context>"},
            {"role": "user", "content": "latest"},
        ]
        sent = llm._openai_request_messages(llm.GPT_6_LUNA_MODEL, messages, responses_api=True)

        parts = sent[1]["content"]
        self.assertEqual([part["type"] for part in parts], ["input_image", "input_text"])
        self.assertEqual(parts[-1]["prompt_cache_breakpoint"], {"mode": "explicit"})

    def test_text_only_models_never_receive_image_inputs(self):
        image = self._store()
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(__iter__=lambda _self: iter(()))
        with patch.object(llm, "groq_client", client):
            list(llm.get_llm_response_stream(self._conversation(image), llm.GPT_OSS_120B_MODEL))

        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertTrue(all(isinstance(message["content"], str) for message in sent))
        self.assertTrue(all(IMAGE_INPUTS_KEY not in message for message in sent))


_LARGE_IMAGE = {"id": "a" * 48, "name": "photo.png", "width": 2048, "height": 1536}
_SMALL_IMAGE = {"id": "c" * 48, "name": "photo.png", "width": 10, "height": 10}


class ImageBudgetTests(unittest.TestCase):

    def test_images_are_budgeted_by_patches_not_by_their_encoded_size(self):
        # 2048x1536 は 64x48=3,072 パッチで、上限 2,500 に頭打ちして 1.2 倍する。
        # 2048x1536 is 3,072 patches, capped at 2,500 and multiplied by 1.2.
        self.assertEqual(estimate_image_input_tokens([_LARGE_IMAGE]), 3000)
        with_image = estimate_messages_tokens([{"role": "user", "content": "hi", IMAGE_INPUTS_KEY: [_LARGE_IMAGE]}])
        without_image = estimate_messages_tokens([{"role": "user", "content": "hi"}])
        self.assertGreaterEqual(with_image - without_image, 3000)
        self.assertLess(with_image - without_image, 3100)

    def test_history_selection_keeps_the_latest_images_and_drops_older_ones_past_the_budget(self):
        messages = [
            {"role": "user", "content": "old question", IMAGE_INPUTS_KEY: [_LARGE_IMAGE]},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new question", IMAGE_INPUTS_KEY: [_LARGE_IMAGE]},
        ]
        roomy = select_recent_messages(messages, 10_000)
        self.assertEqual([IMAGE_INPUTS_KEY in message for message in roomy], [True, False, True])

        tight = select_recent_messages(messages, 3_100)
        self.assertIn(IMAGE_INPUTS_KEY, tight[-1])
        self.assertTrue(all(IMAGE_INPUTS_KEY not in message for message in tight[:-1]))

    def test_recovery_context_keeps_the_images_of_the_current_request(self):
        base = build_recovery_base_messages(
            [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "old", IMAGE_INPUTS_KEY: [_LARGE_IMAGE]},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "now", IMAGE_INPUTS_KEY: [_LARGE_IMAGE]},
            ]
        )
        self.assertEqual(base[-1][IMAGE_INPUTS_KEY], [_LARGE_IMAGE])
        self.assertTrue(all(IMAGE_INPUTS_KEY not in message for message in base[:-1]))


class ChatPostImageGateTests(_UploadRootTestCase):
    def _use_case(self):
        deps = MagicMock()
        deps.web.jsonify = lambda payload, status_code=200: JSONResponse(payload, status_code=status_code)
        return ChatPostUseCase(deps, default_model="gpt-6-luna"), deps

    def _turn(self, model):
        return _ChatPostTurn(
            request=None,
            session={"user_id": 42},
            auth_limit_service=None,
            llm_daily_limit_service=None,
            chat_generation_service=None,
            authenticated=True,
            user_id=42,
            model=model,
            room_mode="normal",
            chat_room_id="room-1",
            attached_files=[{"name": "photo.png", "data_base64": _image_base64()}],
        )

    def test_images_for_a_text_only_model_are_rejected_before_anything_is_stored(self):
        use_case, deps = self._use_case()
        response = asyncio.run(use_case._store_user_message(self._turn("openai/gpt-oss-120b")))

        self.assertEqual(response.status_code, 400)
        deps.persistence.store_user_message_and_load_turn_context.assert_not_called()
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_luna_images_are_stored_and_named_alongside_the_message(self):
        use_case, deps = self._use_case()
        deps.persistence.store_user_message_and_load_turn_context.return_value = {"messages": []}
        turn = self._turn("gpt-6-luna")

        self.assertIsNone(asyncio.run(use_case._store_user_message(turn)))

        call = deps.persistence.store_user_message_and_load_turn_context.call_args
        self.assertEqual(call.args[3], ["photo.png"])
        stored_images = call.kwargs["attached_images"]
        self.assertEqual([image.name for image in stored_images], ["photo.png"])
        self.assertTrue(chat_image_belongs_to(stored_images[0].id, "user:42"))


class ChatHistoryImageSerializationTests(unittest.TestCase):

    def _node(self):
        return {
            "id": 1,
            "parent_id": None,
            "message": "hello",
            "sender": "user",
            "timestamp": None,
            "attached_file_names": '["photo.png"]',
            "attached_images": [_SMALL_IMAGE, {"id": "../escape"}],
        }

    def test_llm_history_and_display_history_carry_only_valid_image_references(self):
        llm_messages = ChatRepository._path_to_llm_messages([self._node()])
        self.assertEqual(llm_messages[0]["attached_images"], [_SMALL_IMAGE])

        entry = ChatRepository(MagicMock())._serialize_path_node(self._node(), {None: [1]})
        self.assertEqual(entry["attached_images"], [_SMALL_IMAGE])
        self.assertEqual(entry["attached_file_names"], ["photo.png"])


class TemporaryRoomImageReferenceTests(unittest.TestCase):
    def test_in_memory_rooms_report_the_images_they_reference(self):
        store = EphemeralChatStore(3600)
        image = {"id": "b" * 48, "name": "photo.png", "width": 10, "height": 10}
        with patch.object(store, "_get_redis", return_value=None), patch(
            "services.ephemeral_store.is_redis_configured", return_value=False
        ):
            store.create_room("sid", "room", "title")
            store.append_message("sid", "room", "user", "hello", attached_images=[image])
            self.assertEqual(store.list_referenced_image_ids(), {"b" * 48})

    def test_unreadable_redis_reports_unknown_instead_of_nothing(self):
        store = EphemeralChatStore(3600)
        with patch.object(store, "_get_redis", return_value=None), patch(
            "services.ephemeral_store.is_redis_configured", return_value=True
        ):
            self.assertIsNone(store.list_referenced_image_ids())


if __name__ == "__main__":
    unittest.main()
