"""Index the FK child columns and constrain MCP OAuth client references.

Revision ID: 20260913_02
Revises: 20260913_01
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260913_02"
down_revision: Union[str, Sequence[str], None] = "20260913_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand only: every statement here adds an index or a NOT VALID foreign key.
    # A previous Blue/Green color keeps reading and writing these tables unchanged.
    # 追加のみ: 索引と NOT VALID の外部キーを足すだけなので、旧バージョンが動いていても
    # 読み書きの挙動は変わりません。
    #
    # CREATE INDEX を CONCURRENTLY にしていない理由 / Why these are not CONCURRENTLY:
    # 対象はいずれも chat_history のような大表ではなく、1ルームあたり数件の memory_facts、
    # 1クライアント/1グラントにつき数行の mcp_oauth_*、ユーザーごとに上限のある user_skills
    # などです。CONCURRENTLY は op.get_context().autocommit_block() を必要とし、revision 単位
    # のトランザクションを失います。途中で失敗すると INVALID な索引が残り、その後始末は索引の
    # 削除になりますが、scripts/check_migration_safety.py は upgrade 内の索引削除を拒否するため、
    # 運用外の手作業が必要になります。既存 67 revision もすべて通常の CREATE INDEX です。
    # None of these tables is chat_history-sized: memory_facts holds a few rows per room, the
    # mcp_oauth_* tables a few rows per client or grant, user_skills is capped per user.
    # CONCURRENTLY would require op.get_context().autocommit_block(), giving up the per-revision
    # transaction and leaving an INVALID index behind on failure, which only an index removal can
    # clear -- and check_migration_safety.py rejects index removals inside an upgrade.

    # remember_facts() looks rooms up by (chat_room_id, scope, lower(fact)).  The existing
    # partial index is filtered on is_active = TRUE, which that query does not constrain,
    # so PostgreSQL could only answer it with a sequential scan of memory_facts.
    op.create_index(
        "idx_memory_facts_room_scope_fact",
        "memory_facts",
        ["chat_room_id", "scope", sa.text("lower(fact)")],
        unique=False,
        if_not_exists=True,
    )

    # Child columns of an ON DELETE SET NULL / CASCADE foreign key need their own index,
    # or deleting one parent row scans the whole child table.  The referential action never
    # matches NULL, so each index is partial.
    op.create_index(
        "idx_memory_facts_source_message_id",
        "memory_facts",
        ["source_message_id"],
        unique=False,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_guest_prompt_submissions_claimed_by_user",
        "guest_prompt_submissions",
        ["claimed_by_user_id"],
        unique=False,
        postgresql_where=sa.text("claimed_by_user_id IS NOT NULL"),
        if_not_exists=True,
    )
    # idx_user_skills_user_source_prompt / idx_task_with_examples_active_user_source_prompt
    # both lead with user_id, so neither can serve a delete of one prompt.
    op.create_index(
        "idx_user_skills_source_prompt_id",
        "user_skills",
        ["source_prompt_id"],
        unique=False,
        postgresql_where=sa.text("source_prompt_id IS NOT NULL"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_task_with_examples_source_prompt_id",
        "task_with_examples",
        ["source_prompt_id"],
        unique=False,
        postgresql_where=sa.text("source_prompt_id IS NOT NULL"),
        if_not_exists=True,
    )
    # idx_mcp_oauth_codes_expiry does not lead with grant_id, so revoking a grant scanned
    # the authorization-code table.
    op.create_index(
        "idx_mcp_oauth_codes_grant_id",
        "mcp_oauth_authorization_codes",
        ["grant_id"],
        unique=False,
        if_not_exists=True,
    )

    # mcp_oauth_grants / _authorization_codes / _tokens all store client_id as bare TEXT:
    # 20260713_01 gave user_id and grant_id a REFERENCES clause but left client_id without
    # one, so deleting a client orphans its grants and tokens.
    for table, index_name in (
        ("mcp_oauth_grants", "idx_mcp_oauth_grants_client_id"),
        ("mcp_oauth_authorization_codes", "idx_mcp_oauth_codes_client_id"),
        ("mcp_oauth_tokens", "idx_mcp_oauth_tokens_client_id"),
    ):
        op.create_index(index_name, table, ["client_id"], unique=False, if_not_exists=True)

    # NOT VALID は既存行を検査しないため、孤児が残っていても ALTER は失敗しません。孤児行を
    # 消して整合させるのは Contract 側の判断（バックアップ必須）なので、この revision では
    # 一切データを触らず、以後の行追加・行更新と親削除時の CASCADE だけを有効にします。
    # VALIDATE CONSTRAINT は、下の SELECT が 0 件であることを確認してから別 revision で
    # 実行してください。
    #
    #   SELECT 'mcp_oauth_grants' AS table_name, COUNT(*) FROM mcp_oauth_grants g
    #     WHERE NOT EXISTS (SELECT 1 FROM mcp_oauth_clients c WHERE c.client_id = g.client_id)
    #   UNION ALL SELECT 'mcp_oauth_authorization_codes', COUNT(*)
    #     FROM mcp_oauth_authorization_codes a
    #     WHERE NOT EXISTS (SELECT 1 FROM mcp_oauth_clients c WHERE c.client_id = a.client_id)
    #   UNION ALL SELECT 'mcp_oauth_tokens', COUNT(*) FROM mcp_oauth_tokens t
    #     WHERE NOT EXISTS (SELECT 1 FROM mcp_oauth_clients c WHERE c.client_id = t.client_id);
    #
    # NOT VALID skips the scan of existing rows, so pre-existing orphans cannot fail this
    # ALTER.  The constraint still fires on every later insert or change of client_id and on
    # parent deletes,
    # which is what stops new orphans.  Removing the old ones is a reviewed Contract step;
    # run the query above and only then VALIDATE the constraints in a separate revision.
    for constraint_name, table in (
        ("fk_mcp_oauth_grants_client_id", "mcp_oauth_grants"),
        ("fk_mcp_oauth_authorization_codes_client_id", "mcp_oauth_authorization_codes"),
        ("fk_mcp_oauth_tokens_client_id", "mcp_oauth_tokens"),
    ):
        op.create_foreign_key(
            constraint_name,
            table,
            "mcp_oauth_clients",
            ["client_id"],
            ["client_id"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )


def downgrade() -> None:
    for constraint_name, table in (
        ("fk_mcp_oauth_tokens_client_id", "mcp_oauth_tokens"),
        ("fk_mcp_oauth_authorization_codes_client_id", "mcp_oauth_authorization_codes"),
        ("fk_mcp_oauth_grants_client_id", "mcp_oauth_grants"),
    ):
        op.drop_constraint(constraint_name, table, type_="foreignkey")
    for index_name, table in (
        ("idx_mcp_oauth_tokens_client_id", "mcp_oauth_tokens"),
        ("idx_mcp_oauth_codes_client_id", "mcp_oauth_authorization_codes"),
        ("idx_mcp_oauth_grants_client_id", "mcp_oauth_grants"),
        ("idx_mcp_oauth_codes_grant_id", "mcp_oauth_authorization_codes"),
        ("idx_task_with_examples_source_prompt_id", "task_with_examples"),
        ("idx_user_skills_source_prompt_id", "user_skills"),
        ("idx_guest_prompt_submissions_claimed_by_user", "guest_prompt_submissions"),
        ("idx_memory_facts_source_message_id", "memory_facts"),
        ("idx_memory_facts_room_scope_fact", "memory_facts"),
    ):
        op.drop_index(index_name, table_name=table, if_exists=True)
