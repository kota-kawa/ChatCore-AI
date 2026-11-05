"""AGENTS.md や ARCHITECTURE.md などの文書が書くファイル・ディレクトリのパス参照が、リポジトリに実在するかを検
証するスクリプト（CI で実行する）。

Verifies that the file and directory paths mentioned in documents such as AGENTS.md and ARCHITECTURE.md exist in the repository (run in CI).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]

# 日本語: パス参照を検証する文書です。README.md は公開向けで外部リンクが多いため対象外にしています。
# English: Documents whose path references are verified. README.md is public-facing and link-heavy, so it is left out.
DOCUMENT_GLOBS = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "docs/*.md",
    "docs/**/*.md",
    "frontend/STYLING_STRATEGY.md",
    "frontend/DESIGN_TOKENS.md",
    ".github/BRANCH_PROTECTION.md",
)

# 日本語: git 管理外・一時ファイルとして文書が意図的に言及するパスです。存在しなくても失敗にしません。
# English: Paths the docs mention on purpose although they are untracked or temporary. Missing ones are not failures.
KNOWN_UNTRACKED: frozenset[str] = frozenset(
    {
        # 秘密情報、一時成果物、依存物、削除済み文書など、存在確認から除外する参照。
        ".env",  # secrets, gitignored
        ".playwright-mcp/",  # Playwright MCP output, gitignored
        "docker-compose.local.yml",  # developer-local compose override, gitignored
        "frontend/pages/__ui_probe.tsx",  # temporary probe page that must never be committed
        "frontend/node_modules",  # installed dependencies
        "browsers.json",  # lives inside a borrowed Playwright node_modules tree
        "db/performance_indexes.sql",  # deleted file; ADR 0004 records its removal
        "システムデザイン.md",  # former document that was split into docs/; named for provenance only
    }
)

# 日本語: 文書ごとに、相対パスの起点として追加で試すディレクトリです。
#         `STYLING_STRATEGY.md` は `pages/lp/lp.css` のように `public/static/css/` からの相対で書きます。
# English: Extra base directories tried per document.
#          `STYLING_STRATEGY.md` writes stylesheet paths relative to `public/static/css/`, e.g. `pages/lp/lp.css`.
DOCUMENT_BASES: dict[str, tuple[str, ...]] = {
    "frontend/STYLING_STRATEGY.md": ("frontend/public/static/css", "frontend/public"),
}

# 日本語: バッククォートで囲まれた語のうち、パスとして検証する形です。空白・ワイルドカード・プレースホルダを含む語は対象外です。
# English: Backtick spans treated as paths. Spans with whitespace, wildcards or placeholders are skipped.
BACKTICK_PATTERN = re.compile(r"`([^`\s]+)`")
LINK_PATTERN = re.compile(r"\]\(([^)\s]+)\)")
PATH_LIKE = re.compile(r"^\.?\.?/?[\w.-]+(/[\w.-]+)*/?$")
FILE_EXTENSIONS = (".md", ".py", ".ts", ".tsx", ".cjs", ".css", ".yml", ".yaml", ".json", ".toml", ".txt", ".sh", ".conf", ".png", ".gif")
URL_PREFIXES = ("http://", "https://", "mailto:")

# 日本語: ルート直下の文書が `frontend/` を省いて書く相対パス（`hooks/chat_page/` など）を許容するための追加の基準ディレクトリです。
# English: Extra base directory so root-level docs may abbreviate frontend paths such as `hooks/chat_page/`.
FALLBACK_BASES = ("frontend",)


def tracked_paths() -> frozenset[str]:
    """git で追跡されているファイルと、無視されていない未追跡ファイルの一覧を返す。`git add` の前にローカルで実行しても通るようにするため。
    git が使えない場合は、ファイルシステムを直接走査する。

    Tracked files plus untracked files that are not ignored, so a local run before `git add` still passes.
    Falls back to walking the filesystem when git is unavailable.
    """
    try:
        tracked = _git_ls_files()
        untracked = _git_ls_files("--others", "--exclude-standard")
    except OSError, subprocess.CalledProcessError:
        return frozenset(str(path.relative_to(REPO_ROOT)) for path in REPO_ROOT.rglob("*") if path.is_file() and ".git" not in path.parts)
    return tracked | untracked


def _git_ls_files(*options: str) -> frozenset[str]:
    """`git ls-files -z` の結果（リポジトリ相対パス）を集合で返す。

    Return the repository-relative paths from `git ls-files -z` as a set.
    """
    output = subprocess.run(["git", "ls-files", "-z", *options], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout
    return frozenset(entry for entry in output.split("\0") if entry)


class PathIndex:
    """リポジトリ内のファイルとディレクトリの存在を、パス参照の検証用にすばやく引ける索引。

    Index of the repository's files and directories for fast existence lookups when verifying path references.
    """

    def __init__(self, files: Iterable[str]) -> None:
        self.files = frozenset(files)
        self.directories = frozenset(str(parent) for file in self.files for parent in Path(file).parents if str(parent) != ".")
        self.unique_basenames = frozenset(name for name, count in Counter(Path(file).name for file in self.files).items() if count == 1)

    def exists(self, candidate: str) -> bool:
        """末尾の `/` を除いたパスが、追跡ファイルまたはディレクトリとして存在するかを返す。

        Return whether the path (without a trailing `/`) exists as a tracked file or directory.
        """
        normalized = candidate.rstrip("/")
        return normalized in self.files or normalized in self.directories

    def resolve(self, reference: str, document: Path) -> bool:
        """文書内のパス参照が実在するかを、文書のあるディレクトリ・ルート・追加の基準ディレクトリの順に試して判定する。

        Decide whether a path reference in a document exists, trying the document's directory, the repo
        root and extra base directories in turn.
        """
        extra_bases = (*DOCUMENT_BASES.get(document.as_posix(), ()), *FALLBACK_BASES)
        bases = (document.parent, Path("."), *(Path(base) for base in extra_bases))
        for base in bases:
            joined = (base / reference).as_posix()
            normalized = _collapse_parent_segments(re.sub(r"^(\./)+", "", joined))
            if normalized is not None and self.exists(normalized):
                return True
        # 日本語: `variables.css` のようなファイル名だけの参照は、同名の追跡ファイルが 1 つだけあるときに限り有効とみなします。
        #         同名ファイルが複数あるとどれを指すか決まらないため、文書側でディレクトリを付けて書きます。
        # English: Bare file names such as `variables.css` count as valid only when exactly one tracked file has that name.
        #          With several same-named files the reference is ambiguous, so the document must qualify it with a directory.
        return "/" not in reference.rstrip("/") and reference in self.unique_basenames


def _collapse_parent_segments(path: str) -> str | None:
    """パス中の `..` を畳み込む。リポジトリの外へ出てしまう場合は None を返す。

    Collapse `..` segments in a path; return None if it would escape the repository.
    """
    parts: list[str] = []
    for part in Path(path).parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def iter_references(text: str) -> Iterator[str]:
    """1 行の中から、Markdown リンクの宛先（`#` 以降を除く）とバッククォートで囲まれた語を取り出す。

    Yield the Markdown link targets (minus any `#` anchor) and the backtick-quoted spans found in one line.
    """
    for match in LINK_PATTERN.finditer(text):
        yield match.group(1).split("#", 1)[0]
    for match in BACKTICK_PATTERN.finditer(text):
        yield match.group(1)


def is_path_reference(reference: str) -> bool:
    # 日本語: 先頭が `/` の語は `/api/chat` のような URL 経路なので検証しません。
    #         拡張子も末尾の `/` も無い語（`next/head`、モデル ID など）はパスと判定しません。
    # English: A leading `/` marks a URL route such as `/api/chat`, not a repository path.
    #          Spans with neither an extension nor a trailing `/` (`next/head`, model ids) are not treated as paths.
    if not reference or reference.startswith(URL_PREFIXES) or reference.startswith(("#", "/")):
        return False
    if not PATH_LIKE.match(reference):
        return False
    if reference.endswith("/"):
        return True
    return reference.endswith(FILE_EXTENSIONS)


def iter_documents() -> Iterator[Path]:
    """DOCUMENT_GLOBS に一致する文書を、重複なく順に返す。

    Yield the documents matching DOCUMENT_GLOBS, without duplicates.
    """
    seen: set[Path] = set()
    for pattern in DOCUMENT_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def check_document(document: Path, index: PathIndex) -> list[str]:
    """1 つの文書を行ごとに調べ、実在しないパス参照を「文書:行: 参照」の形で集めて返す。

    Scan one document line by line and return the nonexistent path references as "document:line: reference" messages.
    """
    relative_document = document.relative_to(REPO_ROOT)
    failures: list[str] = []
    for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), start=1):
        for reference in iter_references(line):
            if not is_path_reference(reference) or reference in KNOWN_UNTRACKED:
                continue
            if not index.resolve(reference, relative_document):
                failures.append(f"{relative_document}:{line_number}: `{reference}` does not exist in the repository")
    return failures


def main() -> int:
    """すべての文書のパス参照を検証し、壊れた参照があれば標準エラーに出して 1 を返す。

    Verify the path references in every document; print broken ones to stderr and return 1 if any exist.
    """
    index = PathIndex(tracked_paths())
    failures = [failure for document in iter_documents() for failure in check_document(document, index)]
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(f"{len(failures)} broken path reference(s). Fix the path or add it to KNOWN_UNTRACKED with a reason.", file=sys.stderr)
        return 1
    print("All documented path references exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
