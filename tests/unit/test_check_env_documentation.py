# `.env.example` と実行時に読まれる環境変数の同期を検証するチェッカーのテストです。
# Tests for the checker that keeps `.env.example` in sync with the environment variables read at runtime.

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_env_documentation as checker  # noqa: E402


# 一時ディレクトリへ最小構成のリポジトリを作り、実際の `.env.example` に依存せず検証します。
# Build a minimal repository in a temporary directory so the checks never depend on the real `.env.example`.
class CheckEnvDocumentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "services").mkdir()

    # 疑似リポジトリへ `.env.example` と実行時モジュールを書き出します。
    # Write the `.env.example` and the runtime module into the fake repository.
    def _write(self, env_example: str, module_source: str, module_name: str = "settings.py") -> None:
        (self.root / ".env.example").write_text(env_example, encoding="utf-8")
        (self.root / "services" / module_name).write_text(module_source, encoding="utf-8")

    # 実行時に読まれているのに `.env.example` へ記載がない変数は、エラーとして報告されます。
    # A variable read at runtime but absent from `.env.example` is reported as an error.
    def test_variable_read_but_undocumented_is_reported(self) -> None:
        self._write(
            "DOCUMENTED=value\n",
            "import os\n\nDOCUMENTED = os.getenv('DOCUMENTED')\nSECRET = os.getenv('UNDOCUMENTED_TOKEN')\n",
        )
        errors = checker.check_documentation(self.root)
        self.assertEqual(errors, ["UNDOCUMENTED_TOKEN is read by runtime code but missing from .env.example"])

    # `.env.example` にあるのに誰も読んでいない変数は、エラーとして報告されます。
    # A variable documented in `.env.example` that nothing reads is reported as an error.
    def test_documented_but_unread_is_reported(self) -> None:
        self._write(
            "USED=value\n# コメント行は無視されます / comment lines are ignored\nDEAD_SETTING=1\n",
            "import os\n\nUSED = os.getenv('USED')\n",
        )
        errors = checker.check_documentation(self.root)
        self.assertEqual(errors, ["DEAD_SETTING is documented in .env.example but nothing reads it"])

    # 記載と実際の読み取りが一致していれば、エラーは報告されません。
    # No error is reported when the documentation and the actual reads match.
    def test_matching_documentation_reports_no_error(self) -> None:
        self._write(
            "# Section\nFIRST=1\nSECOND=two\nexport THIRD=3\n",
            "import os\n\nFIRST = os.getenv('FIRST')\nSECOND = os.environ['SECOND']\nTHIRD = os.environ.get('THIRD')\n",
        )
        self.assertEqual(checker.check_documentation(self.root), [])

    # ヘルパー関数へ変数名を渡す呼び出しも、名前を解決して読み取りとして扱います。
    # A call that passes the variable name into a helper is resolved and counted as a read.
    def test_helper_function_argument_is_resolved(self) -> None:
        self._write(
            "VIA_HELPER=1\n",
            "import os\n\n\n"
            "def _env(name, default=None):\n"
            "    return os.environ.get(name, default)\n\n\n"
            "VALUE = _env('VIA_HELPER', '1')\n",
        )
        self.assertEqual(checker.check_documentation(self.root), [])

    # 変数名がモジュール定数を経由して渡される場合も解決します。
    # A variable name passed through a module-level constant is resolved as well.
    def test_module_constant_name_is_resolved(self) -> None:
        self._write(
            "TOKEN_FROM_CONSTANT=placeholder\n",
            "import os\n\nTOKEN_ENV = 'TOKEN_FROM_CONSTANT'\nTOKEN = os.getenv(TOKEN_ENV)\n",
        )
        self.assertEqual(checker.check_documentation(self.root), [])

    # アプリ自身が値を設定する `os.environ[...] = ...` は設定項目ではないため、記載を求めません。
    # An assignment where the app sets the value itself is not a configuration knob, so no entry is required.
    def test_environ_assignment_is_not_treated_as_read(self) -> None:
        self._write("", "import os\n\nos.environ['SET_BY_APP'] = '1'\n")
        self.assertEqual(checker.check_documentation(self.root), [])

    # 名前を動的に組み立てている箇所は、解決できない旨をエラーとして報告します。
    # A site that builds the name dynamically is reported as an unresolvable error.
    def test_dynamic_name_is_reported_as_unresolved(self) -> None:
        self._write("", "import os\n\n\ndef read(suffix):\n    return os.getenv(f'PREFIX_{suffix}')\n")
        errors = checker.check_documentation(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("could not be resolved statically", errors[0])

    # 許可リストの変数は、Python が読まなくても記載を残せます。
    # An allowlisted variable may stay documented even though no Python code reads it.
    def test_allowlisted_variable_is_accepted(self) -> None:
        self._write("POSTGRES_WORK_MEM=16MB\n", "import os\n\nUNUSED = os\n")
        self.assertIn("POSTGRES_WORK_MEM", checker.DEPLOY_ONLY_VARIABLES)
        self.assertEqual(checker.check_documentation(self.root), [])

    # `.env.example` が存在しない場合は、その旨をエラーとして報告します。
    # A missing `.env.example` is reported as an error.
    def test_missing_env_example_is_reported(self) -> None:
        errors = checker.check_documentation(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("is missing", errors[0])

    # 実リポジトリでは `.env` を読まないことを、走査対象の定義から確認します。
    # Confirm from the scanned-source definition that the real `.env` is never read.
    def test_runtime_sources_do_not_include_dotenv(self) -> None:
        self.assertNotIn(".env", checker.RUNTIME_SOURCES)


if __name__ == "__main__":
    unittest.main()
