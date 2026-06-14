# AlembicのマイグレーションファイルのSQL構文に関する静的解析テスト。
# Static analysis tests for SQL syntax in Alembic migration files.

import ast
import re
import unittest
from pathlib import Path

# マイグレーションファイルが存在するディレクトリのパスを取得
# Get the directory path where migration files are located
MIGRATIONS_DIR = Path(__file__).parents[2] / "alembic" / "versions"

# op.execute() への呼び出しからSQL文字列リテラルを抽出する正規表現
# Regular expression to extract SQL string literals passed to op.execute()
_OP_EXECUTE_SQL = re.compile(
    r'op\.execute\(\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')\s*\)',
    re.DOTALL,
)


# 全てのop.execute()呼び出しからファイル名とSQLブロックのペアを取得します。
# Return (filename, sql_block) pairs for every op.execute() call found.
def _all_migration_sql_blocks():
    results = []
    # マイグレーションディレクトリ内のすべてのPythonファイルをソートして読み込む
    # Sort and read all Python files in the migrations directory
    for p in sorted(MIGRATIONS_DIR.glob("*.py")):
        content = p.read_text()
        for m in _OP_EXECUTE_SQL.finditer(content):
            sql = m.group(1) if m.group(1) is not None else m.group(2)
            results.append((p.name, sql))
    return results


# 指定されたASTノードからリビジョン値（revision/down_revision）を読み取ります。
# Read revision or down_revision values from the given AST node.
def _read_revision_value(node):
    # 代入文、または型注釈付きの代入文から変数名と値を取得
    # Get variable names and values from assign or annotated assign AST nodes
    if isinstance(node, ast.Assign):
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        value = node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names = [node.target.id]
        value = node.value
    else:
        return None, None

    # revisionまたはdown_revisionの値を評価して返却
    # Evaluate and return revision or down_revision values
    if "revision" in names or "down_revision" in names:
        return names, ast.literal_eval(value)

    return None, None


# 全てのリビジョンとdown_revisionの関係からリビジョングラフを構築します。
# Build the revision graph using all revisions and down_revisions.
def _migration_revision_graph():
    revisions = {}
    down_revisions = {}

    # 各マイグレーションファイルをパースしてリビジョン情報を収集
    # Parse each migration file to collect revision information
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        values = {}
        for node in ast.parse(path.read_text()).body:
            names, value = _read_revision_value(node)
            if not names:
                continue
            for name in names:
                if name in {"revision", "down_revision"}:
                    values[name] = value

        revision = values.get("revision")
        revisions[revision] = path.name
        down_revisions[revision] = values.get("down_revision")

    # 親リビジョンから子リビジョンへのマッピングを構築
    # Build child mapping from parent revisions
    children = {revision: [] for revision in revisions}
    for revision, down_revision in down_revisions.items():
        parents = (
            down_revision
            if isinstance(down_revision, (list, tuple))
            else (down_revision,)
        )
        for parent in parents:
            if parent in children:
                children[parent].append(revision)

    return revisions, down_revisions, children


# マイグレーション履歴の構造（リビジョングラフ）をテストするクラス。
# Test class for verifying the structure of the migration revision graph.
class MigrationRevisionGraphTest(unittest.TestCase):
    # マイグレーション履歴にヘッド（末尾）が1つだけ存在することを確認します。
    # Ensure that the migrations have only a single head revision.
    def test_migrations_have_single_head(self):
        revisions, down_revisions, children = _migration_revision_graph()
        # 子リビジョンが存在しないノードをヘッドとして抽出
        # Extract nodes with no child revisions as heads
        heads = sorted(revision for revision, child_revisions in children.items() if not child_revisions)

        self.assertEqual(
            len(heads),
            1,
            "Alembic must have a single head so `alembic upgrade head` works in CD. "
            f"Heads: {[(revision, revisions[revision], down_revisions[revision]) for revision in heads]}",
        )


# トリガー関数内のCASE式でPostgreSQLでエラーになるパターンがないか検証するクラス。
# Test class to check for PostgreSQL-incompatible CASE syntax in triggers.
class MigrationTriggerCaseExpressionTest(unittest.TestCase):
    """
    Guard against mixing simple-CASE selectors with boolean WHEN branches.

    PostgreSQL's simple CASE syntax is:
        CASE <selector> WHEN <value> THEN ... END

    It compares <selector> to each <value> using equality.  If the selector
    is text (e.g. TG_OP) and a WHEN branch is a boolean expression (e.g.
    NEW.deleted_at IS NOT NULL), PostgreSQL raises:
        operator does not exist: text = boolean

    The fix is to use a *searched* CASE:
        CASE WHEN TG_OP = '...' THEN ... WHEN NEW.col IS NOT NULL THEN ... END
    """

    # Matches:  CASE TG_OP ... WHEN NEW.<col>  or  WHEN OLD.<col>
    # A WHEN clause that starts with NEW./OLD. in a simple-CASE block is always
    # a boolean condition, which is incompatible with a text selector.
    _SIMPLE_CASE_BOOL_WHEN = re.compile(
        r"\bCASE\s+TG_OP\b.*?\bWHEN\s+(?:NEW|OLD)\.",
        re.DOTALL | re.IGNORECASE,
    )

    # CASE TG_OP での条件分岐内にレコードフィールド(NEW/OLD)の比較が混在していないかを検証します。
    # Verify that CASE TG_OP does not contain NEW/OLD record field comparisons in WHEN clauses.
    def test_no_simple_case_tg_op_with_record_field_when(self):
        """CASE TG_OP must not have NEW.<col> or OLD.<col> as a WHEN value."""
        # エラーの原因となる構文パターンを含むマイグレーションファイルをリストアップ
        # List up migration files that contain syntax patterns causing the error
        violations = [
            filename
            for filename, sql in _all_migration_sql_blocks()
            if self._SIMPLE_CASE_BOOL_WHEN.search(sql)
        ]
        self.assertFalse(
            violations,
            "Migration(s) contain `CASE TG_OP WHEN NEW.<col>` or "
            "`CASE TG_OP WHEN OLD.<col>`, which causes "
            "'operator does not exist: text = boolean' at runtime.\n"
            "Use a searched CASE instead:\n"
            "  CASE\n"
            "    WHEN TG_OP = 'INSERT' THEN 'created'\n"
            "    WHEN NEW.deleted_at IS NOT NULL ... THEN 'soft_deleted'\n"
            "    ELSE 'updated'\n"
            "  END\n"
            f"Offending files: {violations}",
        )


# トリガー関数内の操作名文字列がVARCHAR(16)制限を超えていないかを検証するクラス。
# Test class to check if operation name string lengths in trigger functions are within VARCHAR(16).
class MigrationTriggerOperationLengthTest(unittest.TestCase):
    """
    Guard against operation strings that exceed the VARCHAR(16) column width
    in *_versions tables (operation VARCHAR(16) NOT NULL).
    """

    # Capture every string literal that follows a THEN keyword inside a CASE
    # expression within a CREATE FUNCTION / DO $$ block.
    _THEN_STRING = re.compile(r"\bTHEN\s+'([^']{17,})'", re.IGNORECASE)

    # トリガー関数内のTHEN節の操作名文字列が16文字以下であることを検証します。
    # Verify that all operation name string literals after THEN are at most 16 characters.
    def test_operation_values_fit_in_varchar16(self):
        """String literals after THEN in trigger functions must be ≤16 chars."""
        violations = []
        # 全てのSQLブロックで、THENの後に続く文字列の長さをチェック
        # Check the length of strings following THEN in all SQL blocks
        for filename, sql in _all_migration_sql_blocks():
            for match in self._THEN_STRING.finditer(sql):
                violations.append((filename, match.group(1)))
        self.assertFalse(
            violations,
            "THEN string(s) in migrations exceed VARCHAR(16): "
            f"{violations}",
        )


if __name__ == "__main__":
    unittest.main()
