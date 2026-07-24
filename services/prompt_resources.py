"""Validation and normalization helpers for text resources bundled with SKILL posts."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import PurePosixPath


MAX_SKILL_RESOURCES = 10
MAX_SKILL_RESOURCE_PATH_LENGTH = 255
MAX_SKILL_RESOURCE_BYTES = 256 * 1024
MAX_SKILL_RESOURCES_TOTAL_BYTES = 1024 * 1024

SKILL_RESOURCE_ROLES = frozenset({"script", "reference", "config", "other"})

_ALLOWED_EXTENSIONS = frozenset(
    {
        ".bash",
        ".c",
        ".cc",
        ".cfg",
        ".conf",
        ".cpp",
        ".cs",
        ".css",
        ".csv",
        ".cxx",
        ".go",
        ".gql",
        ".graphql",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".kts",
        ".lua",
        ".md",
        ".mdx",
        ".mjs",
        ".php",
        ".pl",
        ".proto",
        ".ps1",
        ".py",
        ".r",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)
_ALLOWED_EXTENSIONLESS_NAMES = frozenset(
    {"dockerfile", "makefile", "gemfile", "rakefile", "license", "readme"}
)
_SECRET_EXTENSIONS = frozenset(
    {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer"}
)
_SECRET_NAMES = frozenset(
    {
        "authorized_keys",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
        "secrets.json",
    }
)
_LANGUAGE_BY_SUFFIX = {
    ".bash": "shell",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".lua": "lua",
    ".md": "markdown",
    ".mdx": "mdx",
    ".mjs": "javascript",
    ".php": "php",
    ".pl": "perl",
    ".proto": "protobuf",
    ".ps1": "powershell",
    ".py": "python",
    ".r": "r",
    ".rb": "ruby",
    ".rs": "rust",
    ".scss": "scss",
    ".sh": "shell",
    ".sql": "sql",
    ".svelte": "svelte",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}
_MIME_BY_SUFFIX = {
    ".js": "text/javascript",
    ".jsx": "text/javascript",
    ".json": "application/json",
    ".mjs": "text/javascript",
    ".toml": "application/toml",
    ".ts": "text/typescript",
    ".tsx": "text/typescript",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_resource_path(value: str) -> str:
    """Return a safe canonical POSIX-relative resource path."""
    path = str(value or "").strip()
    if not path:
        raise ValueError("リソースの path は必須です。")
    if len(path) > MAX_SKILL_RESOURCE_PATH_LENGTH:
        raise ValueError(
            f"リソースの path は {MAX_SKILL_RESOURCE_PATH_LENGTH} 文字以内で指定してください。"
        )
    if "\\" in path or _CONTROL_CHARACTER_RE.search(path):
        raise ValueError("リソースの path に使用できない文字が含まれています。")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or path.startswith("/") or any(
        part in {"", ".", ".."} for part in path.split("/")
    ):
        raise ValueError("リソースの path は安全な相対パスで指定してください。")

    normalized = parsed.as_posix()
    lower_path = normalized.casefold()
    lower_name = parsed.name.casefold()
    suffix = parsed.suffix.casefold()
    if lower_path == "skill.md":
        raise ValueError("SKILL.md はSKILL定義用の予約パスです。")
    if lower_name == ".env" or lower_name.startswith(".env."):
        raise ValueError(".env ファイルは投稿できません。")
    if lower_name in _SECRET_NAMES or suffix in _SECRET_EXTENSIONS:
        raise ValueError("秘密鍵や認証情報を含む可能性があるファイルは投稿できません。")
    if suffix not in _ALLOWED_EXTENSIONS and lower_name not in _ALLOWED_EXTENSIONLESS_NAMES:
        raise ValueError(f"このファイル形式は投稿できません: {parsed.name}")
    return normalized


def validate_resource_content(value: str) -> str:
    """Validate that resource content is UTF-8 text within the per-file limit."""
    content = str(value)
    if "\x00" in content:
        raise ValueError("リソース本文にNUL文字は使用できません。")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("リソース本文は有効なUTF-8テキストにしてください。") from exc
    if len(encoded) > MAX_SKILL_RESOURCE_BYTES:
        raise ValueError(
            f"リソース1件のサイズは {MAX_SKILL_RESOURCE_BYTES} バイト以内にしてください。"
        )
    return content


def infer_resource_language(path: str) -> str:
    """Infer a display language identifier from a validated path."""
    return _LANGUAGE_BY_SUFFIX.get(PurePosixPath(path).suffix.casefold(), "text")


def infer_resource_media_type(path: str) -> str:
    """Infer a safe text media type from a validated path."""
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in _MIME_BY_SUFFIX:
        return _MIME_BY_SUFFIX[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed if guessed and guessed.startswith("text/") else "text/plain"


def resource_size_bytes(content: str) -> int:
    return len(content.encode("utf-8"))


def resource_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
