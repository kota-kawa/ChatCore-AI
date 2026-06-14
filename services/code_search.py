from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# 検索対象ディレクトリ（優先度順）
_SEARCH_DIRS = [
    "blueprints",
    "services",
    "frontend/components",
    "frontend/hooks",
    "frontend/pages",
    "frontend/scripts",
    "frontend/lib",
]

# 除外パスのキーワード
_EXCLUDE_PATH_FRAGMENTS = (
    "node_modules",
    ".next",
    "__pycache__",
    ".git",
    "alembic/versions",
    ".min.",
    "bundle.",
    "services/code_search.py",
    "services/manual_rag.py",
)

CONTEXT_LINES = 30       # マッチ行の前後に含める行数
MAX_SNIPPET_CHARS = 900  # 1スニペット当たりの最大文字数
MAX_SNIPPETS = 4         # 返すスニペット上限
GREP_TIMEOUT = 5         # grep タイムアウト（秒）

# 日本語アプリ用語 → 英語コード識別子マッピング
_JA_TO_EN: dict[str, list[str]] = {
    "チャット": ["chat"],
    "ルーム": ["room"],
    "ログイン": ["login", "auth"],
    "ログアウト": ["logout"],
    "認証": ["auth", "verify"],
    "設定": ["settings", "config"],
    "プロンプト": ["prompt"],
    "タスク": ["task"],
    "メモ": ["memo"],
    "共有": ["share"],
    "モデル": ["model", "llm"],
    "ストリーミング": ["stream", "sse"],
    "エージェント": ["agent"],
    "アバター": ["avatar"],
    "テーマ": ["theme"],
    "パスキー": ["passkey"],
    "メッセージ": ["message"],
    "ユーザー": ["user"],
    "エラー": ["error"],
    "キャッシュ": ["cache"],
    "セッション": ["session"],
    "プロフィール": ["profile"],
    "アップロード": ["upload"],
    "削除": ["delete"],
    "作成": ["create"],
    "検索": ["search"],
}


@dataclass
class CodeSnippet:
    rel_path: str
    start_line: int
    end_line: int
    match_line: int
    content: str

    @property
    def lang(self) -> str:
        return "python" if self.rel_path.endswith(".py") else "typescript"


def _extract_search_terms(query: str) -> list[str]:
    """クエリから grep に使うキーワードを抽出する。ASCII 優先、日本語はマッピング経由。"""
    terms: list[str] = []

    # ASCII 英数字の識別子（3文字以上）
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", query):
        terms.append(word.lower())

    # 日本語 → 英語マッピング
    for ja, en_list in _JA_TO_EN.items():
        if ja in query:
            terms.extend(en_list)

    # 重複排除して最大5キーワード
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:5]


def _is_excluded(path: str) -> bool:
    return any(frag in path for frag in _EXCLUDE_PATH_FRAGMENTS)


def _grep(term: str) -> list[tuple[str, int]]:
    """term を含むファイルパスと行番号のリストを返す。"""
    matches: list[tuple[str, int]] = []

    for rel_dir in _SEARCH_DIRS:
        search_path = PROJECT_ROOT / rel_dir
        if not search_path.exists():
            continue

        cmd = [
            "grep", "-rn", "-i",
            "--include=*.py", "--include=*.ts", "--include=*.tsx",
            term,
            str(search_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=GREP_TIMEOUT)
            for line in proc.stdout.splitlines():
                if _is_excluded(line):
                    continue
                parts = line.split(":", 2)
                if len(parts) >= 2:
                    try:
                        matches.append((parts[0], int(parts[1])))
                    except ValueError:
                        continue
        except (subprocess.TimeoutExpired, OSError):
            logger.warning("grep timed out or failed for term=%s dir=%s", term, rel_dir)

    return matches


def _read_snippet(file_path: str, match_line: int) -> CodeSnippet | None:
    try:
        path = Path(file_path)
        all_lines = path.read_text(encoding="utf-8").splitlines()
        total = len(all_lines)

        start = max(0, match_line - CONTEXT_LINES - 1)
        end = min(total, match_line + CONTEXT_LINES)
        content = "\n".join(all_lines[start:end])

        if len(content) > MAX_SNIPPET_CHARS:
            content = content[:MAX_SNIPPET_CHARS] + "\n# ... (省略)"

        try:
            rel_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            rel_path = file_path

        return CodeSnippet(
            rel_path=rel_path,
            start_line=start + 1,
            end_line=end,
            match_line=match_line,
            content=content,
        )
    except Exception:
        logger.exception("Failed to read snippet: %s", file_path)
        return None


def search_codebase(query: str, max_snippets: int = MAX_SNIPPETS) -> str:
    """クエリに関連するコードスニペットを grep で探して文字列で返す。

    複数キーワードにマッチするファイルを優先して返す。
    返り値が空文字列の場合は該当なし。
    """
    terms = _extract_search_terms(query)
    if not terms:
        return ""

    # ファイルごとにマッチしたキーワード数をスコアとして集計
    file_scores: dict[str, int] = {}
    file_first_match: dict[str, int] = {}  # ファイルの最初のマッチ行

    for term in terms:
        seen_in_term: set[str] = set()
        for file_path, line_num in _grep(term):
            if file_path not in seen_in_term:
                seen_in_term.add(file_path)
                file_scores[file_path] = file_scores.get(file_path, 0) + 1
                if file_path not in file_first_match:
                    file_first_match[file_path] = line_num

    # スコア降順でソートしたファイルから上位を選択
    top_files = sorted(file_scores, key=lambda f: file_scores[f], reverse=True)[:max_snippets]
    all_matches: list[tuple[str, int]] = [(f, file_first_match[f]) for f in top_files]

    if not all_matches:
        return ""

    snippets: list[CodeSnippet] = []
    for file_path, line_num in all_matches:
        snippet = _read_snippet(file_path, line_num)
        if snippet:
            snippets.append(snippet)
        if len(snippets) >= max_snippets:
            break

    if not snippets:
        return ""

    parts = ["【コードベース検索結果】"]
    for s in snippets:
        parts.append(
            f"\n**{s.rel_path}** (行 {s.start_line}–{s.end_line}, マッチ行 {s.match_line})\n"
            f"```{s.lang}\n{s.content}\n```"
        )
    return "\n".join(parts)
