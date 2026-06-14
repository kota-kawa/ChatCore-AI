"""Add ON DELETE CASCADE to chat_rooms and prompts user FKs.

Revision ID: 20260322_01
Revises: 20260321_03
Create Date: 2026-03-22 10:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260322_01"
down_revision: Union[str, Sequence[str], None] = "20260321_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    """
    [JP] 現在データベース内に存在するテーブル名のセットを返します。
    [EN] Return a set of table names existing in the database.
    """
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _replace_user_fk(table_name: str, constraint_name: str, *, cascade: bool) -> None:
    """
    [JP] 指定されたテーブルのユーザーIDに関する外部キー制約を、指定されたON DELETE設定で再作成します。
    [EN] Recreate the foreign key constraint on user_id for the specified table with the specified ON DELETE behavior.
    """
    desired_delete_action = "CASCADE" if cascade else "NO ACTION"
    # [JP] 外部キー制約を追加できるように、親のいない孤立レコードをあらかじめ削除します。
    # [EN] Clean up orphan records before adding the foreign key constraint.
    orphan_cleanup_sql = f"""
    DELETE FROM {table_name} target
    WHERE NOT EXISTS (
        SELECT 1
        FROM users u
        WHERE u.id = target.user_id
    )
    """
    op.execute(orphan_cleanup_sql)
    # [JP] 既存の制約定義を調査し、必要に応じて削除および再作成を行います。
    # [EN] Check existing constraint definition and drop/recreate it if needed.
    op.execute(
        f"""
        DO $$
        DECLARE
            existing_name text;
            existing_definition text;
        BEGIN
            SELECT con.conname, pg_get_constraintdef(con.oid)
              INTO existing_name, existing_definition
              FROM pg_constraint con
              JOIN pg_class rel
                ON rel.oid = con.conrelid
              JOIN pg_namespace nsp
                ON nsp.oid = rel.relnamespace
             WHERE con.contype = 'f'
               AND nsp.nspname = current_schema()
               AND rel.relname = '{table_name}'
               AND con.confrelid = 'users'::regclass
               AND con.conkey = ARRAY[
                    (
                        SELECT attnum
                        FROM pg_attribute
                        WHERE attrelid = rel.oid
                          AND attname = 'user_id'
                    )
               ]::smallint[]
             LIMIT 1;

            -- [JP] 既存の制約の ON DELETE 挙動が期待と異なる場合は一度削除します
            -- [EN] Drop existing constraint if its ON DELETE behavior does not match the desired one
            IF existing_name IS NOT NULL AND position('ON DELETE {desired_delete_action}' in existing_definition) = 0 THEN
                EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', '{table_name}', existing_name);
                existing_name := NULL;
            END IF;

            -- [JP] 制約が存在しない、または削除された場合は、期待する設定で新規作成します
            -- [EN] Create the constraint with desired settings if it does not exist or was dropped
            IF existing_name IS NULL THEN
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE {desired_delete_action}',
                    '{table_name}',
                    '{constraint_name}'
                );
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """
    [JP] chat_rooms および prompts テーブルの users 参照外部キーを ON DELETE CASCADE に変更します。
    [EN] Modify user reference foreign keys in chat_rooms and prompts tables to ON DELETE CASCADE.
    """
    tables = _existing_tables()
    # [JP] chat_rooms テーブルが存在する場合、外部キーを CASCADE に更新
    # [EN] If chat_rooms table exists, update foreign key to CASCADE
    if "chat_rooms" in tables and "users" in tables:
        _replace_user_fk("chat_rooms", "fk_chat_rooms_user", cascade=True)
    # [JP] prompts テーブルが存在する場合、外部キーを CASCADE に更新
    # [EN] If prompts table exists, update foreign key to CASCADE
    if "prompts" in tables and "users" in tables:
        _replace_user_fk("prompts", "fk_prompts_user", cascade=True)


def downgrade() -> None:
    """
    [JP] chat_rooms および prompts テーブルの users 参照外部キーを ON DELETE NO ACTION に戻します。
    [EN] Revert user reference foreign keys in chat_rooms and prompts tables to ON DELETE NO ACTION.
    """
    tables = _existing_tables()
    # [JP] chat_rooms テーブルが存在する場合、外部キーを NO ACTION に更新
    # [EN] If chat_rooms table exists, update foreign key to NO ACTION
    if "chat_rooms" in tables and "users" in tables:
        _replace_user_fk("chat_rooms", "fk_chat_rooms_user", cascade=False)
    # [JP] prompts テーブルが存在する場合、外部キーを NO ACTION に更新
    # [EN] If prompts table exists, update foreign key to NO ACTION
    if "prompts" in tables and "users" in tables:
        _replace_user_fk("prompts", "fk_prompts_user", cascade=False)
