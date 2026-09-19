"""Fail CI/deploy when a new migration violates the expand/contract policy.

The historical migration chain contains operations that were safe for the
release that introduced them but are unsafe while another Blue/Green color is
still serving traffic.  This guard treats the existing head as a compatibility
baseline and checks every descendant revision for newly introduced destructive
DDL or unreviewed data changes.

Usage:

    python3 scripts/check_migration_safety.py --baseline 20260824_03
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
DATA_REVIEW_MARKER = "# migration-review: approved-data-backfill"

_DESTRUCTIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "DROP TABLE/COLUMN/CONSTRAINT/INDEX",
        re.compile(r"\bDROP\s+(?:TABLE|COLUMN|CONSTRAINT|INDEX)\b", re.IGNORECASE),
    ),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    ("DELETE FROM", re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    (
        "op.drop_*",
        re.compile(r"\bop\.drop_(?:column|table|index|constraint)\s*\(", re.IGNORECASE),
    ),
    (
        "ALTER ... SET NOT NULL",
        re.compile(r"\bSET\s+NOT\s+NULL\b", re.IGNORECASE),
    ),
    (
        "CREATE UNIQUE INDEX",
        re.compile(r"\bCREATE\s+UNIQUE\s+INDEX\b", re.IGNORECASE),
    ),
)
_DATA_CHANGE_PATTERN = re.compile(r"\bUPDATE\s+[A-Za-z_]", re.IGNORECASE)

# 稼働中テーブルの書き込みを止める DDL。安全な綴り（CONCURRENTLY / NOT VALID）が
# 同じ文の中にあるかで判定が変わるため、upgrade 全体ではなく SQL 文ごとに照合する。
# Index builds and CHECK validations block writes on a live table. Whether they are safe
# depends on CONCURRENTLY / NOT VALID appearing in the same statement, so unlike
# _DESTRUCTIVE_PATTERNS these are matched per SQL statement.
BLOCKING_INDEX_LABEL = "CREATE INDEX without CONCURRENTLY"
VALIDATED_CHECK_LABEL = "ADD CONSTRAINT ... CHECK without NOT VALID"
BLOCKING_INDEX_REVIEW_MARKER = "# migration-review: approved-blocking-index"
VALIDATED_CHECK_REVIEW_MARKER = "# migration-review: approved-validated-check"

_CREATE_INDEX_SQL = re.compile(
    r"\bCREATE\s+INDEX\s+(?!CONCURRENTLY\b)"
    r"(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+(?:ONLY\s+)?\"?(?P<table>\w+)",
    re.IGNORECASE,
)
_ADD_CHECK_SQL = re.compile(r"\bADD\s+CONSTRAINT\b[\s\S]*?\bCHECK\s*\(", re.IGNORECASE)
_NOT_VALID_SQL = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)
_CREATE_TABLE_SQL = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(?P<table>\w+)", re.IGNORECASE
)

# 後から追加した検査パターンに該当する、すでに main へ入って適用済みの revision。
# 適用済み migration は書き換えられない（AGENTS.md）ため、当時の判断を revision 単位で
# 明示的に除外し、新しい revision にだけ新パターンを適用する。
# Revisions already merged and applied before these checks existed.  Applied migrations must
# not be rewritten, so each historical decision is grandfathered explicitly per revision and
# the new checks only constrain new revisions.
_GRANDFATHERED_VIOLATIONS: dict[str, frozenset[str]] = {
    # embedding_status は同じ revision で追加した列で、server_default 'pending' 以外の値を
    # 持つ行が存在しえないため制約は常に検証済みになる。今から NOT VALID へ貼り替えるには
    # DROP CONSTRAINT が必要で、そのほうが危険（無制約の窓ができる）。
    # The column was added in the same revision with server_default 'pending', so no row can
    # violate the constraint.  Re-laying it as NOT VALID would need a DROP CONSTRAINT, which
    # opens an unconstrained window and is strictly worse.
    "20260826_01": frozenset({VALIDATED_CHECK_LABEL}),
    # user_skills は 20260828_01 で作られた 1 ユーザーあたり上限のある小表。
    # user_skills was created one revision earlier and is capped per user.
    "20260829_01": frozenset({BLOCKING_INDEX_LABEL}),
    # chat_rooms への索引追加。適用済みで、作り直しは索引の削除を伴うため行わない。
    # Already applied on chat_rooms; rebuilding it would require dropping the index.
    "20260901_01": frozenset({BLOCKING_INDEX_LABEL}),
    # 非 CONCURRENTLY を選んだ理由を revision 本体のコメントで説明済み。
    # The revision itself documents why CONCURRENTLY was not used.
    "20260913_02": frozenset({BLOCKING_INDEX_LABEL}),
}


@dataclass(frozen=True)
class MigrationSource:
    revision: str
    down_revision: str | tuple[str, ...] | None
    path: Path
    source: str


def _literal_assignment(module: ast.Module, name: str) -> Any:
    for node in module.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(value)
    raise ValueError(f"Migration is missing literal {name!r} assignment.")


def load_migrations(directory: Path = MIGRATIONS_DIR) -> dict[str, MigrationSource]:
    migrations: dict[str, MigrationSource] = {}
    for path in sorted(directory.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source, filename=str(path))
        revision = _literal_assignment(module, "revision")
        down_revision = _literal_assignment(module, "down_revision")
        if isinstance(down_revision, list):
            down_revision = tuple(str(value) for value in down_revision)
        elif down_revision is not None:
            down_revision = str(down_revision)
        migration = MigrationSource(str(revision), down_revision, path, source)
        if migration.revision in migrations:
            raise ValueError(f"Duplicate migration revision: {migration.revision}")
        migrations[migration.revision] = migration
    return migrations


def _parents(migration: MigrationSource) -> tuple[str, ...]:
    if migration.down_revision is None:
        return ()
    if isinstance(migration.down_revision, tuple):
        return migration.down_revision
    return (migration.down_revision,)


def descendants_after_baseline(
    migrations: dict[str, MigrationSource], baseline: str
) -> list[MigrationSource]:
    if baseline not in migrations:
        raise ValueError(f"Baseline revision {baseline!r} was not found.")

    children: dict[str, list[str]] = {revision: [] for revision in migrations}
    for migration in migrations.values():
        for parent in _parents(migration):
            if parent in children:
                children[parent].append(migration.revision)

    descendants: list[MigrationSource] = []
    pending = sorted(children[baseline])
    while pending:
        revision = pending.pop(0)
        migration = migrations[revision]
        descendants.append(migration)
        pending.extend(sorted(children[revision]))
    return descendants


def _upgrade_source(source: str) -> str:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    return ""


def _op_calls(upgrade_module: ast.Module, attribute: str) -> Iterator[ast.Call]:
    """Yield every ``op.<attribute>(...)`` call in the upgrade."""
    for node in ast.walk(upgrade_module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == attribute
        ):
            yield node


def _string_argument(call: ast.Call, position: int, keyword: str) -> str | None:
    """Read one literal string argument, by position or by keyword."""
    if len(call.args) > position:
        value = call.args[position]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    for node in call.keywords:
        if (
            node.arg == keyword
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _keyword_is_true(call: ast.Call, keyword: str) -> bool:
    for node in call.keywords:
        if node.arg == keyword and isinstance(node.value, ast.Constant):
            return node.value.value is True
    return False


def _sql_statements(upgrade_module: ast.Module | None) -> list[str]:
    """Split every SQL string literal in the upgrade into separate statements."""
    if upgrade_module is None:
        return []
    statements: list[str] = []
    for node in ast.walk(upgrade_module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            statements.extend(node.value.split(";"))
    return statements


def _created_tables(upgrade_module: ast.Module | None, statements: list[str]) -> set[str]:
    """Collect tables this upgrade creates itself.

    索引を貼っても他セッションから見えない表なので、CONCURRENTLY は不要。
    No other session can see a table this revision creates, so indexing it blocks nobody.
    """
    tables: set[str] = set()
    for statement in statements:
        for match in _CREATE_TABLE_SQL.finditer(statement):
            tables.add(match.group("table").lower())
    if upgrade_module is not None:
        for call in _op_calls(upgrade_module, "create_table"):
            name = _string_argument(call, 0, "table_name")
            if name is not None:
                tables.add(name.lower())
    return tables


def _blocking_ddl_violations(
    migration: MigrationSource, upgrade_module: ast.Module | None
) -> list[str]:
    """Flag index builds and CHECK validations that lock a live table for writes."""
    statements = _sql_statements(upgrade_module)
    created_tables = _created_tables(upgrade_module, statements)
    index_targets: list[str] = []
    unsafe_check = False
    for statement in statements:
        index_targets.extend(
            match.group("table").lower() for match in _CREATE_INDEX_SQL.finditer(statement)
        )
        if _ADD_CHECK_SQL.search(statement) and not _NOT_VALID_SQL.search(statement):
            unsafe_check = True
    if upgrade_module is not None:
        for call in _op_calls(upgrade_module, "create_index"):
            if _keyword_is_true(call, "postgresql_concurrently"):
                continue
            # 表名が定数でない（ループ変数など）場合は既存表として扱う。
            # A non-literal table name is treated as an existing table.
            index_targets.append((_string_argument(call, 1, "table_name") or "").lower())
        for call in _op_calls(upgrade_module, "create_check_constraint"):
            if not _keyword_is_true(call, "postgresql_not_valid"):
                unsafe_check = True

    violations: list[str] = []
    if (
        any(table not in created_tables for table in index_targets)
        and BLOCKING_INDEX_REVIEW_MARKER not in migration.source
    ):
        violations.append(BLOCKING_INDEX_LABEL)
    if unsafe_check and VALIDATED_CHECK_REVIEW_MARKER not in migration.source:
        violations.append(VALIDATED_CHECK_LABEL)
    return violations


def classify_upgrade(migration: MigrationSource) -> list[str]:
    """Return policy violations found in one migration's upgrade function."""
    upgrade = _upgrade_source(migration.source)
    violations: list[str] = []
    for label, pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(upgrade):
            violations.append(label)
    upgrade_module: ast.Module | None
    try:
        upgrade_module = ast.parse(upgrade)
    except SyntaxError:
        upgrade_module = None
    violations.extend(_blocking_ddl_violations(migration, upgrade_module))
    if upgrade_module is not None:
        for node in ast.walk(upgrade_module):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "op"
                and node.func.attr == "alter_column"
            ):
                continue
            nullable = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "nullable"),
                None,
            )
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                violations.append("op.alter_column nullable=False")
                break
    if _DATA_CHANGE_PATTERN.search(upgrade) and DATA_REVIEW_MARKER not in migration.source:
        violations.append("unreviewed UPDATE data change")
    return violations


def check_migrations(baseline: str) -> list[tuple[MigrationSource, list[str]]]:
    migrations = load_migrations()
    violations: list[tuple[MigrationSource, list[str]]] = []
    for migration in descendants_after_baseline(migrations, baseline):
        grandfathered = _GRANDFATHERED_VIOLATIONS.get(migration.revision, frozenset())
        reasons = [
            reason for reason in classify_upgrade(migration) if reason not in grandfathered
        ]
        if reasons:
            violations.append((migration, reasons))
    return violations


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        default="20260824_03",
        help="Last revision known to be compatible with the previous release.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        migrations = load_migrations()
        descendants = descendants_after_baseline(migrations, args.baseline)
        violations = check_migrations(args.baseline)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"Migration safety check failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Migration safety baseline {args.baseline}: "
        f"checked {len(descendants)} descendant revision(s)."
    )
    if not violations:
        print("No new destructive or unreviewed data-changing upgrades found.")
        return 0

    print("Unsafe migration upgrade(s) detected:", file=sys.stderr)
    for migration, reasons in violations:
        print(
            f"  {migration.revision} ({migration.path.name}): {', '.join(reasons)}",
            file=sys.stderr,
        )
    print(
        "Split destructive work into a post-deploy Contract step, or add the "
        f"explicit review marker only for an audited backfill: {DATA_REVIEW_MARKER}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
