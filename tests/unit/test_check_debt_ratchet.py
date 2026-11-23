# 技術的負債の件数を基準値と比べるチェッカーのテストです。
# Tests for the checker that compares technical-debt counts against the baseline.

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
_SPEC = importlib.util.spec_from_file_location("check_debt_ratchet", REPO_ROOT / "scripts" / "check_debt_ratchet.py")
assert _SPEC is not None and _SPEC.loader is not None
checker = importlib.util.module_from_spec(_SPEC)
# 日本語: dataclass の定義はモジュールが sys.modules にあることを前提にするため、実行前に登録します。
# English: Dataclass definitions expect the module in sys.modules, so register it before executing.
sys.modules[_SPEC.name] = checker
_SPEC.loader.exec_module(checker)


class CountTest(unittest.TestCase):
    # 宣言の値の色だけを数え、ID セレクタやコメントの中は数えません。
    # Only colors in declaration values count; ID selectors and comments do not.
    def test_css_hex_colors_skip_selectors_and_comments(self) -> None:
        css = "#add, .a { color: #fff; border: 1px solid #12345678 }\n/* #000 */\n@media (x) { #face { background: #abcdef; } }"
        self.assertEqual(checker.count_css_hex_colors(css), 3)

    def test_direct_env_reads_count_attribute_access_and_imports(self) -> None:
        source = "import os\nfrom os import getenv\nA = os.environ.get('A')\nB = os.getenv('B')\nC = getenv('C')\nD = 'os.environ'\n"
        self.assertEqual(checker.count_direct_env_reads(source), 3)

    # 文字列の中に書かれた抑制の書式は、抑制ではないので数えません。
    # Suppression syntax inside a string is not a suppression and does not count.
    def test_python_suppressions_count_comments_only(self) -> None:
        source = "x = 1  # noqa: E501\ny = '# noqa'\nz: int = 'a'  # type: ignore[assignment]\n"
        self.assertEqual(checker.count_suppressions("services/a.py", source), 2)

    def test_python_file_level_suppressions(self) -> None:
        source = "# ruff: noqa: E501\n# mypy: ignore-errors\n"
        self.assertEqual(checker.count_suppressions("services/a.py", source), 2)

    def test_frontend_suppressions(self) -> None:
        source = "// eslint-disable-next-line no-console\n/* @ts-expect-error */\n/** @ts-ignore */\nconst s = 'eslint-disable';\n"
        self.assertEqual(checker.count_suppressions("frontend/lib/a.ts", source), 3)

    def test_lines_count_only_above_limit(self) -> None:
        self.assertEqual(checker.count_lines_over_limit("x\n" * checker.MAX_FILE_LINES), 0)
        self.assertEqual(checker.count_lines_over_limit("x\n" * (checker.MAX_FILE_LINES + 1)), checker.MAX_FILE_LINES + 1)

    def test_scopes_exclude_token_file_env_helper_and_generated_code(self) -> None:
        self.assertFalse(checker.is_css(checker.COLOR_TOKEN_FILE))
        self.assertFalse(checker.is_backend_runtime(checker.ENV_HELPER_FILE))
        self.assertFalse(checker.is_frontend_source("frontend/types/generated/api_schemas.ts"))
        self.assertFalse(checker.is_application_source("tests/unit/test_a.py"))
        self.assertTrue(checker.is_application_source("services/a.py"))


class BaselineTest(unittest.TestCase):
    @staticmethod
    def _counts(**entries: dict[str, int]) -> dict[str, dict[str, int]]:
        return {metric.name: dict(entries.get(metric.name, {})) for metric in checker.METRICS}

    # 基準値に無いファイルに負債が出たら、増加として扱います。
    # Debt in a file missing from the baseline counts as an increase.
    def test_compare_reports_increase_including_new_files(self) -> None:
        current = self._counts(direct_env_reads={"services/a.py": 2, "services/new.py": 1})
        baseline = self._counts(direct_env_reads={"services/a.py": 2})
        increased, decreased = checker.compare(current, baseline)
        self.assertEqual(len(increased), 1)
        self.assertIn("services/new.py: 0 -> 1", increased[0])
        self.assertEqual(decreased, [])

    def test_compare_reports_stale_baseline_when_debt_drops(self) -> None:
        current = self._counts(css_hex_colors={"frontend/a.css": 1})
        baseline = self._counts(css_hex_colors={"frontend/a.css": 3, "frontend/gone.css": 2})
        increased, decreased = checker.compare(current, baseline)
        self.assertEqual(increased, [])
        self.assertEqual(len(decreased), 2)

    # `--update` は下げるだけで、増えた分や新しいファイルは基準値に書き込みません。
    # `--update` only lowers; increases and new files are never written into the baseline.
    def test_lowered_baseline_never_raises_or_adds(self) -> None:
        current = self._counts(lint_type_suppressions={"a.py": 1, "b.py": 5, "new.py": 1})
        baseline = self._counts(lint_type_suppressions={"a.py": 3, "b.py": 4, "gone.py": 2})
        lowered = checker.lowered_baseline(current, baseline)
        self.assertEqual(lowered["lint_type_suppressions"], {"a.py": 1, "b.py": 4})


if __name__ == "__main__":
    unittest.main()
