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


def classify_upgrade(migration: MigrationSource) -> list[str]:
    """Return policy violations found in one migration's upgrade function."""
    upgrade = _upgrade_source(migration.source)
    violations: list[str] = []
    for label, pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(upgrade):
            violations.append(label)
    try:
        upgrade_module = ast.parse(upgrade)
    except SyntaxError:
        upgrade_module = None
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
        reasons = classify_upgrade(migration)
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
