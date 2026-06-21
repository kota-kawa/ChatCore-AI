"""Add projects, project_files tables and chat_rooms.project_id.

Revision ID: 20260621_01
Revises: 20260619_01
Create Date: 2026-06-21 00:00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260621_01"
down_revision: Union[str, Sequence[str], None] = "20260619_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # [JP] projects テーブルの作成（ChatGPT/Claude のプロジェクトに相当するワークスペース）
    # [EN] Create the projects table (a workspace, like ChatGPT/Claude "Projects").
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT '新規プロジェクト',
            instructions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_projects_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] ユーザーごとのプロジェクト一覧取得用インデックス
    # [EN] Index for listing projects per user, newest first.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_projects_user_created_at
            ON projects (user_id, created_at DESC)
        """
    )

    # [JP] project_files テーブルの作成（プロジェクトのナレッジ＝抽出済みテキスト）
    # [EN] Create project_files (project knowledge base: extracted text content).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_files (
            id SERIAL PRIMARY KEY,
            project_id INT NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            content TEXT,
            byte_size INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_project_files_project
                FOREIGN KEY (project_id)
                REFERENCES projects(id)
                ON DELETE CASCADE
        )
        """
    )
    # [JP] プロジェクトのナレッジ取得用インデックス
    # [EN] Index for fetching files of a project.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_project_files_project_id
            ON project_files (project_id, id)
        """
    )

    # [JP] chat_rooms にプロジェクト所属を表す project_id を追加（任意・SET NULL）
    # [EN] Add project_id to chat_rooms (nullable; SET NULL keeps chats on project delete).
    op.execute(
        """
        ALTER TABLE chat_rooms
            ADD COLUMN IF NOT EXISTS project_id INT
        """
    )
    op.execute(
        """
        ALTER TABLE chat_rooms
            ADD CONSTRAINT fk_chat_rooms_project
                FOREIGN KEY (project_id)
                REFERENCES projects(id)
                ON DELETE SET NULL
        """
    )
    # [JP] プロジェクト配下チャットの一覧取得用インデックス
    # [EN] Index for listing chats that belong to a project.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_rooms_project_created_at
            ON chat_rooms (project_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_rooms_project_created_at")
    op.execute("ALTER TABLE chat_rooms DROP CONSTRAINT IF EXISTS fk_chat_rooms_project")
    op.execute("ALTER TABLE chat_rooms DROP COLUMN IF EXISTS project_id")
    op.execute("DROP TABLE IF EXISTS project_files")
    op.execute("DROP TABLE IF EXISTS projects")
