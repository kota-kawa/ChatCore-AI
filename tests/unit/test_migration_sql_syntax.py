"""Static analysis tests for SQL syntax in Alembic migration files.

These tests catch PostgreSQL-incompatible SQL patterns that are syntactically
valid Python strings but fail at runtime when the DB executes them.
"""

import re
import unittest
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[2] / "alembic" / "versions"

# Extracts the string literal passed to every op.execute() call.
# Matches both triple-double-quoted and triple-single-quoted forms.
_OP_EXECUTE_SQL = re.compile(
    r'op\.execute\(\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')\s*\)',
    re.DOTALL,
)


def _all_migration_sql_blocks():
    """Return (filename, sql_block) pairs for every op.execute() call found."""
    results = []
    for p in sorted(MIGRATIONS_DIR.glob("*.py")):
        content = p.read_text()
        for m in _OP_EXECUTE_SQL.finditer(content):
            sql = m.group(1) if m.group(1) is not None else m.group(2)
            results.append((p.name, sql))
    return results


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

    def test_no_simple_case_tg_op_with_record_field_when(self):
        """CASE TG_OP must not have NEW.<col> or OLD.<col> as a WHEN value."""
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


class MigrationTriggerOperationLengthTest(unittest.TestCase):
    """
    Guard against operation strings that exceed the VARCHAR(16) column width
    in *_versions tables (operation VARCHAR(16) NOT NULL).
    """

    # Capture every string literal that follows a THEN keyword inside a CASE
    # expression within a CREATE FUNCTION / DO $$ block.
    _THEN_STRING = re.compile(r"\bTHEN\s+'([^']{17,})'", re.IGNORECASE)

    def test_operation_values_fit_in_varchar16(self):
        """String literals after THEN in trigger functions must be ≤16 chars."""
        violations = []
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
