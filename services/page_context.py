from __future__ import annotations

import logging
import re
from pathlib import Path

from services.agent_capabilities import build_capability_context

logger = logging.getLogger(__name__)

# 日本語: プロジェクトのルートディレクトリ。
# English: Root directory of the project.
PROJECT_ROOT = Path(__file__).parent.parent
MAX_LINES_PER_FILE = 130
MAX_FILES_PER_PAGE = 3

# 日本語: 各URLパターンに対応する画面の説明と読み込むソースコードファイルの定義リスト。
# English: Definition list matching URL patterns to page descriptions and source files to load.
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
        "投稿したプロンプトページ",
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

# 日本語: フロントエンドのソースコードファイルを読み込み、行数制限以内で先頭部分を返します。
# English: Read and return the top lines of a source file up to the specified line limit.
def _read_file_head(rel_path: str, max_lines: int) -> str:
    """ファイルの先頭 max_lines 行を読み取って返す。"""
    full_path = PROJECT_ROOT / rel_path
    if not full_path.exists():
        return ""
    try:
        # 日本語: ファイルが存在し読み込み可能な場合、指定された最大行数分だけテキストを抽出します。
        # English: If the file exists and is readable, extract its text up to the specified line limit.
        lines = full_path.read_text(encoding="utf-8").splitlines()
        head = lines[:max_lines]
        text = "\n".join(head)
        if len(lines) > max_lines:
            text += f"\n// ... ({len(lines) - max_lines} 行省略)"
        return text
    except Exception:
        logger.exception("Failed to read %s", full_path)
        return ""


# 日本語: 現在のURLパスに対応する画面のソースコードおよびAPI機能カタログを結合したコンテキスト文字列を返します。
# English: Build a prompt context string containing relevant source code files and capabilities for the current route.
def get_page_context(pathname: str) -> str:
    """URL パスに対応するページのソースコードを読み取りコンテキスト文字列として返す。"""
    if not pathname:
        return ""

    # 日本語: 定義されたURLマップを検索し、一致するパターンの画面ソースコードを読み込んで結合します。
    # English: Search the defined URL map and read/combine the source files for the matching route.
    for pattern, page_label, file_specs in _PAGE_MAP:
        if pattern.search(pathname):
            parts = [
                build_capability_context(pathname),
                f"\n【現在のページ: {page_label}（{pathname}）のソースコード抜粋】",
            ]
            count = 0
            # 日本語: 該当する各ファイルの先頭部分を読み込み、マークダウンコードブロックとして結合します。
            # English: Read the top portion of each matching file and append it as a markdown code block.
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
