"""Backfill memo and My Context embedding vectors.

Rows written while the embedding provider was broken have `embedding_vector IS NULL`,
and semantic search skips them entirely — fixing the provider alone leaves those rows
permanently invisible. This script fills them in.

Usage (from the repository root):

    python3 scripts/backfill_embeddings.py --dry-run
    python3 scripts/backfill_embeddings.py
    python3 scripts/backfill_embeddings.py --target memos --limit 500

Safe to re-run: by default only rows without a vector are processed, so an interrupted
run resumes where it stopped. Pass --include-existing after changing the embedding model,
when every vector has to be regenerated with the new one.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from blueprints.memo.embeddings import store_embedding as store_memo_embedding  # noqa: E402
from services.context_vault_embeddings import (  # noqa: E402
    build_context_fact_embedding_text,
)
from services.db import get_db_connection  # noqa: E402
from services.embeddings import (  # noqa: E402
    EMBEDDING_MODEL,
    embeddings_available,
    generate_embedding,
)
from services.logging_config import configure_logging  # noqa: E402
from services.memo_ai import build_memo_embedding_text  # noqa: E402
from services.repositories.context_fact_repository import ContextFactRepository  # noqa: E402

logger = logging.getLogger("scripts.backfill_embeddings")

# 1度に読み出す行数。埋め込みは1行ずつ生成するため、DB往復だけをまとめる。
# Rows fetched per round-trip. Embeddings are generated one row at a time, so this only
# batches the database side.
READ_BATCH_SIZE = 200


def _fetch_batch(
    table: str,
    columns: str,
    *,
    after_id: int,
    include_existing: bool,
    batch_size: int,
) -> list[tuple]:
    """Read one keyset-paginated batch, oldest id first."""
    vector_clause = "" if include_existing else " AND embedding_vector IS NULL"
    with get_db_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT id, {columns}
                  FROM {table}
                 WHERE id > %s{vector_clause}
                 ORDER BY id
                 LIMIT %s
                """,
                (after_id, batch_size),
            )
            return list(cursor.fetchall())
        finally:
            cursor.close()


def _count_pending(table: str, *, include_existing: bool) -> int:
    vector_clause = "" if include_existing else " WHERE embedding_vector IS NULL"
    with get_db_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}{vector_clause}")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            cursor.close()


class BackfillStats:
    """Counters for one table's run."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.embedded = 0
        self.skipped_empty = 0
        self.failed = 0

    def report(self) -> str:
        return (
            f"{self.label}: embedded={self.embedded} "
            f"skipped_empty={self.skipped_empty} failed={self.failed}"
        )


def _backfill_table(
    *,
    label: str,
    table: str,
    columns: str,
    build_text,
    store,
    include_existing: bool,
    limit: int | None,
    sleep_seconds: float,
    dry_run: bool,
) -> BackfillStats:
    stats = BackfillStats(label)
    pending = _count_pending(table, include_existing=include_existing)
    logger.info("%s: %s row(s) to process.", label, pending)
    if dry_run or pending == 0:
        return stats

    after_id = 0
    processed = 0
    while True:
        batch_size = READ_BATCH_SIZE
        if limit is not None:
            batch_size = min(batch_size, limit - processed)
        if batch_size <= 0:
            break

        rows = _fetch_batch(
            table,
            columns,
            after_id=after_id,
            include_existing=include_existing,
            batch_size=batch_size,
        )
        if not rows:
            break

        for row in rows:
            row_id = int(row[0])
            after_id = max(after_id, row_id)
            processed += 1

            text = build_text(row)
            if not text.strip():
                stats.skipped_empty += 1
                continue

            embedding = generate_embedding(text)
            if embedding is None:
                stats.failed += 1
                if not embeddings_available():
                    # 連続失敗で埋め込みが停止した。残りを叩き続けても無駄なので中断する。
                    # Consecutive failures paused embeddings; hammering the rest is pointless.
                    logger.error(
                        "%s: embeddings stopped responding after %s row(s); aborting.",
                        label,
                        processed,
                    )
                    return stats
                continue

            store(row_id, embedding)
            stats.embedded += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)

        logger.info("%s: processed %s row(s) so far.", label, processed)

    return stats


def _memo_text(row: tuple) -> str:
    _, title, ai_response = row
    return build_memo_embedding_text(str(title or ""), str(ai_response or ""))


def _fact_text(row: tuple) -> str:
    _, fact_type, title, content = row
    return build_context_fact_embedding_text(
        str(fact_type or ""), str(title or ""), str(content or "")
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("all", "memos", "facts"),
        default="all",
        help="Which table to backfill (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many rows per table.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to wait between embedding calls, to stay under a rate limit.",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Re-embed rows that already have a vector (use after a model change).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many rows would be processed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not args.dry_run and not embeddings_available():
        logger.error(
            "Embeddings are unavailable (model %s). Set OPENAI_API_KEY and retry.",
            EMBEDDING_MODEL,
        )
        return 1

    fact_repository = ContextFactRepository()
    targets = []
    if args.target in ("all", "memos"):
        targets.append(
            {
                "label": "memo_entries",
                "table": "memo_entries",
                "columns": "title, ai_response",
                "build_text": _memo_text,
                "store": lambda row_id, embedding: store_memo_embedding(row_id, embedding),
            }
        )
    if args.target in ("all", "facts"):
        targets.append(
            {
                "label": "context_facts",
                "table": "context_facts",
                "columns": "fact_type, title, content",
                "build_text": _fact_text,
                "store": lambda row_id, embedding: fact_repository.store_embedding(
                    row_id, embedding
                ),
            }
        )

    logger.info("Backfilling embeddings with model %s.", EMBEDDING_MODEL)
    failed = 0
    for target in targets:
        stats = _backfill_table(
            label=str(target["label"]),
            table=str(target["table"]),
            columns=str(target["columns"]),
            build_text=target["build_text"],
            store=target["store"],
            include_existing=args.include_existing,
            limit=args.limit,
            sleep_seconds=args.sleep,
            dry_run=args.dry_run,
        )
        logger.info("%s", stats.report())
        failed += stats.failed

    if failed:
        logger.error("Backfill finished with %s failed row(s); re-run to retry them.", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
