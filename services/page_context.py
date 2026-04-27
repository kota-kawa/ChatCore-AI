from __future__ import annotations

import logging
import re
from pathlib import Path

from services.agent_capabilities import build_capability_context

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
MAX_LINES_PER_FILE = 130
MAX_FILES_PER_PAGE = 3

# URL パターン → (ページ説明, [(ファイルパス, 最大行数), ...])
_PAGE_MAP: list[tuple[re.Pattern[str], str, list[tuple[str, int]]]] = [
    (
        re.compile(r"^/$"),
        "チャットページ（メイン）",
        [
            ("frontend/pages/index.tsx", 130),
            ("frontend/components/chat_page/setup_section.tsx", 100),
            ("frontend/components/chat_page/chat_main_section.tsx", 100),
        ],
    ),
    (
        re.compile(r"^/login$"),
        "ログイン・認証ページ",
        [
            ("frontend/pages/login.tsx", 60),
            ("frontend/components/auth/auth_gateway_page.tsx", 120),
        ],
    ),
    (
        re.compile(r"^/settings$"),
        "設定ページ",
        [
            ("frontend/pages/settings.tsx", 130),
        ],
    ),
    (
        re.compile(r"^/prompt_share/manage"),
        "プロンプト管理ページ",
        [
            ("frontend/pages/prompt_share/manage_prompts.tsx", 130),
        ],
    ),
    (
        re.compile(r"^/prompt_share"),
        "プロンプト共有ページ",
        [
            ("frontend/pages/prompt_share/index.tsx", 100),
            ("frontend/components/prompt_share/prompt_share_page_layout.tsx", 100),
        ],
    ),
    (
        re.compile(r"^/memo$"),
        "メモページ",
        [
            ("frontend/pages/memo.tsx", 130),
        ],
    ),
    (
        re.compile(r"^/shared/memo/"),
        "共有メモ表示ページ",
        [
            ("frontend/pages/shared/memo/[token].tsx", 120),
        ],
    ),
    (
        re.compile(r"^/shared/prompt/"),
        "共有プロンプト表示ページ",
        [
            ("frontend/pages/shared/prompt/[id].tsx", 120),
        ],
    ),
    (
        re.compile(r"^/shared/"),
        "共有チャット表示ページ",
        [
            ("frontend/pages/shared/[token].tsx", 120),
        ],
    ),
    (
        re.compile(r"^/admin"),
        "管理画面",
        [
            ("frontend/pages/admin/index.tsx", 120),
        ],
    ),
]

# ユーザーが操作（クリック・入力等）を依頼しているパターン
_ACTION_REQUEST_PATTERNS = re.compile(
    r"(?:クリック|タップ|押)して(?:ほしい|くれ|ください|もらえ|みて)?"
    r"|(?:入力|記入|書き込)(?:んで|いて|して)(?:ほしい|くれ|ください|もらえ)?"
    r"|(?:操作|実行)して(?:ほしい|くれ|ください|もらえ|みて)?"
    r"|代わりに.{0,30}(?:して|クリック|入力|押)"
    r"|やって(?:ほしい|くれ|ください|もらえ)",
    re.IGNORECASE,
)

# 「今いるページ」を指しているパターン
_PAGE_CONTEXT_PATTERNS = re.compile(
    r"このページ|この画面|今のページ|今の画面|今開いている|現在のページ|現在の画面"
    r"|ここで[はにのを]|ここから|ここに|ここの|ここは"
    r"|このフォーム|この入力欄|このボタン|このモーダル|このタブ"
    r"|どこ[にでから]?(ある|あります|押す|クリック|入力)"
    r"|このアプリの(使い方|操作|機能|画面)",
    re.IGNORECASE,
)


def is_page_specific_query(query: str) -> bool:
    """ユーザーが今開いているページについて質問しているか判定する。"""
    return bool(_PAGE_CONTEXT_PATTERNS.search(query))


def is_action_request(query: str) -> bool:
    """ユーザーがページ上での操作（クリック・入力等）を依頼しているか判定する。"""
    return bool(_ACTION_REQUEST_PATTERNS.search(query))


def _read_file_head(rel_path: str, max_lines: int) -> str:
    """ファイルの先頭 max_lines 行を読み取って返す。"""
    full_path = PROJECT_ROOT / rel_path
    if not full_path.exists():
        return ""
    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
        head = lines[:max_lines]
        text = "\n".join(head)
        if len(lines) > max_lines:
            text += f"\n// ... ({len(lines) - max_lines} 行省略)"
        return text
    except Exception:
        logger.exception("Failed to read %s", full_path)
        return ""


def get_page_context(pathname: str) -> str:
    """URL パスに対応するページのソースコードを読み取りコンテキスト文字列として返す。"""
    if not pathname:
        return ""

    for pattern, page_label, file_specs in _PAGE_MAP:
        if pattern.search(pathname):
            parts = [
                build_capability_context(pathname),
                f"\n【現在のページ: {page_label}（{pathname}）のソースコード抜粋】",
            ]
            count = 0
            for rel_path, max_lines in file_specs:
                if count >= MAX_FILES_PER_PAGE:
                    break
                content = _read_file_head(rel_path, max_lines)
                if not content:
                    continue
                lang = "python" if rel_path.endswith(".py") else "typescript"
                parts.append(f"\n**{rel_path}**\n```{lang}\n{content}\n```")
                count += 1

            if count == 0:
                return ""
            return "\n".join(parts)

    return ""
