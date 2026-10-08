"""生成UIが Web 検索画像を番号で参照する経路（検証・解決・モデルへの一覧）を検証する。

Verifies how a generated UI references web-search images by number: validation, resolution, and
the list handed to the model.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from blueprints.chat.web_search_image_media import get_web_search_image
from services.chat_generation_web_search import ChatGenerationWebSearchMixin
from services.generative_ui import (
    decode_message_parts,
    encode_message_parts,
    normalize_response_with_artifacts,
    validate_artifact_payload,
)
from services.generative_ui_images import (
    attach_web_search_images_to_artifacts,
    build_generated_ui_image_catalog,
)
from services.url_fetcher import FetchedImageContent
from services.user_skills import GENERATIVE_UI_EXECUTION_CONTRACT
from services.web_search_image_proxy import (
    WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX,
    build_web_search_image_proxy_path,
    is_signed_web_search_image_proxy_path,
    resolve_web_search_image_proxy_url,
)

_SELECTIONS = [
    {
        "url": "https://images.example.com/hasedera.jpg?size=large",
        "alt": "長谷寺の観音堂",
        "source_url": "https://travel.example.com/hasedera",
        "source_title": "長谷寺ガイド",
    },
    {
        "url": "https://cdn.example.org/daibutsu.webp",
        "alt": "鎌倉大仏",
        "source_url": "https://travel.example.org/daibutsu",
        "source_title": "鎌倉大仏の歩き方",
    },
]


def _artifact(html: str = '<div id="app"></div>', css: str = "", js: str = "", **extra) -> dict:
    return {"version": 1, "title": "鎌倉", "height": 320, "html": html, "css": css, "js": js, **extra}


def _split_proxy_path(path: str) -> tuple[str, str]:
    signature, token = path[len(WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX) :].split("/")
    return signature, token


class WebSearchImageProxyPathTests(unittest.TestCase):
    def test_signed_path_resolves_back_to_the_selected_url(self):
        url = _SELECTIONS[0]["url"]
        path = build_web_search_image_proxy_path(url)

        self.assertTrue(path.startswith(WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX))
        self.assertTrue(is_signed_web_search_image_proxy_path(path))
        self.assertEqual(resolve_web_search_image_proxy_url(*_split_proxy_path(path)), url)

    def test_signature_of_one_url_does_not_unlock_another(self):
        signature, _ = _split_proxy_path(build_web_search_image_proxy_path(_SELECTIONS[0]["url"]))
        _, other_token = _split_proxy_path(build_web_search_image_proxy_path("https://attacker.example/?leak=secret"))

        self.assertIsNone(resolve_web_search_image_proxy_url(signature, other_token))
        self.assertFalse(
            is_signed_web_search_image_proxy_path(f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{signature}/{other_token}")
        )

    def test_malformed_paths_are_rejected(self):
        signature, token = _split_proxy_path(build_web_search_image_proxy_path(_SELECTIONS[0]["url"]))
        for path in (
            "https://images.example.com/hasedera.jpg",
            f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{signature}/{token}?x=1",
            f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{signature.upper()}/{token}",
            f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{signature}/!!!",
            f"https://evil.example{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{signature}/{token}",
            None,
        ):
            with self.subTest(path=path):
                self.assertFalse(is_signed_web_search_image_proxy_path(path))


class WebSearchImageRouteTests(unittest.TestCase):
    def test_signed_path_relays_the_fetched_image(self):
        signature, token = _split_proxy_path(build_web_search_image_proxy_path(_SELECTIONS[0]["url"]))
        fetched = FetchedImageContent(media_type="image/jpeg", data=b"\xff\xd8jpeg-bytes")
        with patch("blueprints.chat.web_search_image_media.fetch_image_content", return_value=fetched) as fetch:
            response = asyncio.run(get_web_search_image(signature, token))

        fetch.assert_called_once_with(_SELECTIONS[0]["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(response.body, fetched.data)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_unsigned_url_is_never_fetched(self):
        signature, _ = _split_proxy_path(build_web_search_image_proxy_path(_SELECTIONS[0]["url"]))
        _, other_token = _split_proxy_path(build_web_search_image_proxy_path("http://169.254.169.254/latest/meta-data"))
        with patch("blueprints.chat.web_search_image_media.fetch_image_content") as fetch:
            response = asyncio.run(get_web_search_image(signature, other_token))

        fetch.assert_not_called()
        self.assertEqual(response.status_code, 404)

    def test_failed_fetch_answers_404(self):
        signature, token = _split_proxy_path(build_web_search_image_proxy_path(_SELECTIONS[0]["url"]))
        with patch("blueprints.chat.web_search_image_media.fetch_image_content", return_value=None):
            response = asyncio.run(get_web_search_image(signature, token))

        self.assertEqual(response.status_code, 404)


class ArtifactImageReferenceValidationTests(unittest.TestCase):
    def test_numbered_reference_survives_while_an_external_url_is_stripped(self):
        artifact = validate_artifact_payload(
            _artifact(
                html=(
                    '<div id="app"><img src="web-image:1" alt="a">'
                    '<img src="https://images.example.com/x.jpg" alt="b">'
                    '<img src="web-image:1?leak=1" alt="c"></div>'
                ),
                css="#app{background:url(web-image:2)}.x{background:url(https://images.example.com/y.jpg)}",
            )
        )

        self.assertIn('src="web-image:1"', artifact["html"])
        self.assertNotIn("https://images.example.com", artifact["html"])
        self.assertNotIn("leak", artifact["html"])
        self.assertIn("url(web-image:2)", artifact["css"])
        self.assertNotIn("https://images.example.com", artifact["css"])

    def test_images_written_by_the_model_are_dropped_unless_signed(self):
        signed = {
            "ref": 1,
            "url": build_web_search_image_proxy_path(_SELECTIONS[0]["url"]),
            "alt": "長谷寺の観音堂",
            "source_url": "https://travel.example.com/hasedera",
            "source_title": "長谷寺ガイド",
        }
        forged = [
            {**signed, "ref": 2, "url": "https://attacker.example/?leak=secret"},
            {**signed, "ref": 3, "url": f"{WEB_SEARCH_IMAGE_PROXY_PATH_PREFIX}{'0' * 32}/aHR0cHM6Ly9ldmlsLmV4YW1wbGUv"},
            {**signed, "ref": 9},
            {**signed, "ref": 4, "source_url": "javascript:alert(1)"},
        ]

        artifact = validate_artifact_payload(_artifact(images=[signed, *forged]))
        self.assertEqual(artifact["images"], [signed])

        self.assertNotIn("images", validate_artifact_payload(_artifact(images=forged)))

    def test_contract_names_the_reference_the_validator_accepts(self):
        self.assertIn("generated_ui_images", GENERATIVE_UI_EXECUTION_CONTRACT)
        self.assertIn('<img src="web-image:1"', GENERATIVE_UI_EXECUTION_CONTRACT)
        self.assertIn("url(web-image:1)", GENERATIVE_UI_EXECUTION_CONTRACT)


class AttachWebSearchImagesTests(unittest.TestCase):
    def _parts(self, **artifact_fields) -> list[dict]:
        return [
            {"type": "text", "text": "鎌倉の見どころです。"},
            {"type": "sandbox_artifact", "artifact": validate_artifact_payload(_artifact(**artifact_fields))},
        ]

    def test_only_referenced_selected_images_are_attached(self):
        parts = self._parts(
            html='<div id="app"><img src="web-image:2" alt="大仏"></div>',
            js='const missing="web-image:5";',
        )

        attached = attach_web_search_images_to_artifacts(parts, _SELECTIONS)

        assert attached is not None
        self.assertEqual(attached[0], parts[0])
        images = attached[1]["artifact"]["images"]
        self.assertEqual([image["ref"] for image in images], [2])
        self.assertEqual(
            resolve_web_search_image_proxy_url(*_split_proxy_path(images[0]["url"])),
            _SELECTIONS[1]["url"],
        )
        self.assertEqual(images[0]["source_url"], _SELECTIONS[1]["source_url"])
        self.assertEqual(images[0]["alt"], "鎌倉大仏")

    def test_artifact_without_references_or_selections_is_unchanged(self):
        parts = self._parts()
        self.assertEqual(attach_web_search_images_to_artifacts(parts, _SELECTIONS), parts)

        referencing = self._parts(html='<div id="app"><img src="web-image:1" alt="a"></div>')
        self.assertEqual(attach_web_search_images_to_artifacts(referencing, []), referencing)

    def test_attached_images_survive_storage_round_trip(self):
        parts = self._parts(html='<div id="app"><img src="web-image:1" alt="観音堂"></div>')
        attached = attach_web_search_images_to_artifacts(parts, _SELECTIONS)

        decoded = decode_message_parts(encode_message_parts(attached))

        assert attached is not None and decoded is not None
        self.assertEqual(decoded[1]["artifact"]["images"], attached[1]["artifact"]["images"])
        self.assertIn('src="web-image:1"', decoded[1]["artifact"]["html"])

    def test_model_answer_reference_is_resolved_end_to_end(self):
        artifact_json = json.dumps(
            _artifact(html='<div id="app"><img src="web-image:1" alt="観音堂"></div>'),
            ensure_ascii=False,
        )
        normalized = normalize_response_with_artifacts(f"鎌倉です。\n\n```chatcore-artifact\n{artifact_json}\n```")

        attached = attach_web_search_images_to_artifacts(normalized.parts, _SELECTIONS)

        assert attached is not None
        artifact = next(part["artifact"] for part in attached if part["type"] == "sandbox_artifact")
        self.assertEqual([image["ref"] for image in artifact["images"]], [1])


class GeneratedUiImageCatalogTests(unittest.TestCase):
    def test_catalog_lists_references_without_urls(self):
        catalog = build_generated_ui_image_catalog(_SELECTIONS)

        self.assertEqual(
            catalog,
            [
                {"ref": "web-image:1", "alt": "長谷寺の観音堂", "source_title": "長谷寺ガイド"},
                {"ref": "web-image:2", "alt": "鎌倉大仏", "source_title": "鎌倉大仏の歩き方"},
            ],
        )
        self.assertNotIn("example.com", json.dumps(catalog))

    def _with_images(self, *, ui_mode, explicit_ui_opt_out=False, selections=_SELECTIONS) -> dict:
        job = SimpleNamespace(_ui_mode=ui_mode, _explicit_ui_opt_out=explicit_ui_opt_out)
        state = SimpleNamespace(selected_web_search_images=list(selections))
        return ChatGenerationWebSearchMixin._with_generated_ui_images(job, state, {"status": "completed"})

    def test_tool_result_lists_images_when_a_generated_ui_may_be_produced(self):
        for ui_mode in ("2D", "3D", None):
            with self.subTest(ui_mode=ui_mode):
                payload = self._with_images(ui_mode=ui_mode)
                self.assertEqual([image["ref"] for image in payload["generated_ui_images"]], ["web-image:1", "web-image:2"])
                self.assertEqual(payload["status"], "completed")

    def test_tool_result_omits_images_when_no_generated_ui_is_produced(self):
        self.assertNotIn("generated_ui_images", self._with_images(ui_mode="NONE"))
        self.assertNotIn("generated_ui_images", self._with_images(ui_mode="2D", explicit_ui_opt_out=True))
        self.assertNotIn("generated_ui_images", self._with_images(ui_mode="2D", selections=[]))


if __name__ == "__main__":
    unittest.main()
