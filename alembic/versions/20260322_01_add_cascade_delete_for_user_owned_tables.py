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
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _replace_user_fk(table_name: str, constraint_name: str, *, cascade: bool) -> None:
    desired_delete_action = "CASCADE" if cascade else "NO ACTION"
    orphan_cleanup_sql = f"""
    DELETE FROM {table_name} target
    WHERE NOT EXISTS (
        SELECT 1
        FROM users u
        WHERE u.id = target.user_id
    )
    """
    op.execute(orphan_cleanup_sql)
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

            IF existing_name IS NOT NULL AND position('ON DELETE {desired_delete_action}' in existing_definition) = 0 THEN
                EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', '{table_name}', existing_name);
                existing_name := NULL;
            END IF;

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
    tables = _existing_tables()
    if "chat_rooms" in tables and "users" in tables:
        _replace_user_fk("chat_rooms", "fk_chat_rooms_user", cascade=True)
    if "prompts" in tables and "users" in tables:
        _replace_user_fk("prompts", "fk_prompts_user", cascade=True)


def downgrade() -> None:
    tables = _existing_tables()
    if "chat_rooms" in tables and "users" in tables:
        _replace_user_fk("chat_rooms", "fk_chat_rooms_user", cascade=False)
    if "prompts" in tables and "users" in tables:
        _replace_user_fk("prompts", "fk_prompts_user", cascade=False)
