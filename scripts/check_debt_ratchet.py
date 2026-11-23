"""技術的負債の件数をファイルごとに数え、基準値より増えていたら失敗するスクリプト（CI で実行する）。

減った場合も、基準値が古いままだと次に増えても気づけないため失敗にします。`--update` は減った分だけ基準値を下げ、
増えた分は書き込みません。基準値を上げる（ファイルの移動など）ときは基準値ファイルを手で編集し、理由を PR に書きます。

Counts technical-debt markers per file and fails when any count exceeds the baseline (run in CI).
A count below the baseline also fails, because a stale baseline would let the next increase pass unnoticed. `--update`
only lowers the baseline; raising it (for example after moving a file) is a manual edit whose reason goes in the PR.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
BASELINE_PATH = REPO_ROOT / "scripts" / "debt_ratchet_baseline.json"

# 日本語: これを超える行数のファイルは、行数を増やせません。新しいファイルはこの行数以下にします。
# English: Files longer than this may not grow, and new files must stay within it.
MAX_FILE_LINES = 800

# 日本語: 色トークンの正本です。ここだけは 16 進数の色を書けます。
# English: The source of truth for color tokens; the only stylesheet allowed to hold hex colors.
COLOR_TOKEN_FILE = "frontend/public/static/css/base/variables.css"
ENV_HELPER_FILE = "services/env_settings.py"
GENERATED_FRONTEND_DIR = "frontend/types/generated/"
FRONTEND_TEST_DIR = "frontend/tests/"

BACKEND_RUNTIME_DIRS = ("blueprints/", "services/")
PYTHON_DIRS = ("blueprints/", "services/", "scripts/", "tests/")
FRONTEND_SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".mjs", ".cjs")

CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])")
PYTHON_SUPPRESSION = re.compile(r"#\s*(?:(?:ruff|flake8):\s*)?noqa\b|#\s*type:\s*ignore\b|#\s*mypy:\s*ignore-errors\b")
FRONTEND_SUPPRESSION = re.compile(r"(?://|/\*+)\s*(?:eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck)")


def count_css_hex_colors(text: str) -> int:
    """宣言の値に書かれた 16 進数の色を数える。`#abc {` のような ID セレクタは数えない。"""
    count = 0
    # 日本語: `{` で終わる区切りはセレクタ、`;` と `}` で終わる区切りは宣言です。宣言の値だけを見ます。
    # English: Segments ending in `{` are selectors; those ending in `;` or `}` are declarations. Only values are scanned.
    for segment in re.split(r"(?<=[{};])", CSS_COMMENT.sub("", text)):
        if segment.endswith("{") or ":" not in segment:
            continue
        count += len(HEX_COLOR.findall(segment.split(":", 1)[1]))
    return count


def count_direct_env_reads(text: str) -> int:
    """`os.environ`／`os.getenv` と、`os` から `environ`／`getenv` を取り込む import を数える。"""
    count = 0
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            count += node.value.id == "os" and node.attr in {"environ", "getenv"}
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            count += sum(alias.name in {"environ", "getenv"} for alias in node.names)
    return count


def count_lines_over_limit(text: str) -> int:
    """上限を超えたファイルの行数を返す。上限以下なら 0（基準値に載せない）。"""
    lines = len(text.splitlines())
    return lines if lines > MAX_FILE_LINES else 0


def count_python_suppressions(text: str) -> int:
    """コメント中の `# noqa` と `# type: ignore` を数える。文字列の中は数えない。"""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return sum(len(PYTHON_SUPPRESSION.findall(token.string)) for token in tokens if token.type == tokenize.COMMENT)


def count_frontend_suppressions(text: str) -> int:
    return len(FRONTEND_SUPPRESSION.findall(text))


def count_suppressions(path: str, text: str) -> int:
    return count_python_suppressions(text) if path.endswith(".py") else count_frontend_suppressions(text)


def is_css(path: str) -> bool:
    return path.startswith("frontend/") and path.endswith(".css") and path != COLOR_TOKEN_FILE


def is_backend_runtime(path: str) -> bool:
    is_runtime = path == "app.py" or path.startswith(BACKEND_RUNTIME_DIRS)
    return is_runtime and path.endswith(".py") and path != ENV_HELPER_FILE


def is_python(path: str) -> bool:
    return path.endswith(".py") and (path == "app.py" or path.startswith(PYTHON_DIRS))


def is_frontend_source(path: str) -> bool:
    return (
        path.startswith("frontend/")
        and path.endswith(FRONTEND_SOURCE_SUFFIXES)
        and not path.startswith((GENERATED_FRONTEND_DIR, "frontend/public/"))
        and not path.endswith(".d.ts")
    )


def is_application_source(path: str) -> bool:
    """行数を見る対象。テストと生成物は除く。"""
    if is_frontend_source(path):
        return not path.startswith(FRONTEND_TEST_DIR) and ".test." not in path
    return is_python(path) and not path.startswith("tests/")


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    applies_to: Callable[[str], bool]
    count: Callable[[str, str], int]


# 日本語: 数える負債の一覧です。種類を足すときはここに 1 つ足し、`--update` ではなく基準値を手で足します。
# English: The debt markers counted. Add one entry here and add its baseline by hand (not via `--update`).
METRICS: tuple[Metric, ...] = (
    Metric(
        "css_hex_colors",
        f"CSS の生の 16 進数の色（トークンは {COLOR_TOKEN_FILE} に定義する）",
        is_css,
        lambda _path, text: count_css_hex_colors(text),
    ),
    Metric(
        "direct_env_reads",
        f"os.environ／os.getenv の直接読み（{ENV_HELPER_FILE} のヘルパーを使う）",
        is_backend_runtime,
        lambda _path, text: count_direct_env_reads(text),
    ),
    Metric(
        "lines_over_limit",
        f"{MAX_FILE_LINES} 行を超えるファイルの行数（分割して減らす）",
        is_application_source,
        lambda _path, text: count_lines_over_limit(text),
    ),
    Metric(
        "lint_type_suppressions",
        "lint・型検査の抑制コメント（noqa、type: ignore、eslint-disable、@ts-ignore など）",
        lambda path: is_python(path) or is_frontend_source(path),
        count_suppressions,
    ),
)

Counts = dict[str, dict[str, int]]


def candidate_paths() -> list[str]:
    """追跡済みと、無視されていない未追跡のファイル。`git add` の前にローカルで実行しても結果が変わらないようにする。"""
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return sorted({path for path in output.split("\0") if path and (REPO_ROOT / path).is_file()})


def collect_counts(paths: Iterable[str]) -> Counts:
    counts: Counts = {metric.name: {} for metric in METRICS}
    for path in paths:
        metrics = [metric for metric in METRICS if metric.applies_to(path)]
        if not metrics:
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for metric in metrics:
            value = metric.count(path, text)
            if value:
                counts[metric.name][path] = value
    return counts


def load_baseline() -> Counts:
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {metric.name: {str(path): int(value) for path, value in data.get(metric.name, {}).items()} for metric in METRICS}


def write_baseline(baseline: Counts) -> None:
    ordered = {name: dict(sorted(entries.items())) for name, entries in baseline.items()}
    BASELINE_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compare(current: Counts, baseline: Counts) -> tuple[list[str], list[str]]:
    """基準値より増えた項目と、減った（基準値が古い）項目を返す。"""
    increased: list[str] = []
    decreased: list[str] = []
    for metric in METRICS:
        now, allowed = current[metric.name], baseline[metric.name]
        for path in sorted(now.keys() | allowed.keys()):
            actual, limit = now.get(path, 0), allowed.get(path, 0)
            line = f"{metric.name}: {path}: {limit} -> {actual}  ({metric.description})"
            if actual > limit:
                increased.append(line)
            elif actual < limit:
                decreased.append(line)
    return increased, decreased


def lowered_baseline(current: Counts, baseline: Counts) -> Counts:
    """減った分だけ下げた基準値。増えた分や新しいファイルは書き込まない。"""
    return {
        name: {path: min(limit, current[name].get(path, 0)) for path, limit in entries.items() if current[name].get(path, 0)}
        for name, entries in baseline.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="減った分だけ基準値を下げる / lower the baseline where counts dropped")
    args = parser.parse_args(argv)

    current = collect_counts(candidate_paths())
    baseline = load_baseline()
    increased, decreased = compare(current, baseline)

    if args.update:
        write_baseline(lowered_baseline(current, baseline))
        print(f"Lowered {len(decreased)} baseline entries in {BASELINE_PATH.relative_to(REPO_ROOT)}.")
        decreased = []

    if increased:
        print("技術的負債が基準値より増えています。増やさずに実装してください / Debt grew past the baseline:", file=sys.stderr)
        print("\n".join(f"  {line}" for line in increased), file=sys.stderr)
    if decreased:
        print(
            "減った負債があります。`python3 scripts/check_debt_ratchet.py --update` で基準値を下げてコミットしてください"
            " / Debt dropped; lower the baseline with --update and commit it:",
            file=sys.stderr,
        )
        print("\n".join(f"  {line}" for line in decreased), file=sys.stderr)
    if increased or decreased:
        return 1
    print("Debt ratchet: no file exceeds its baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
