# ADR 0004: DB スキーマ変更を Alembic の履歴で管理する

- 状態: Accepted
- 対象: `alembic/`, `alembic/versions/`, `docker/app-entrypoint.sh`

## 背景

複数環境でアプリケーションと PostgreSQL の構造を一致させるには、起動時に暗黙の SQL を実行する方式では適用順序と適用済み状態を追跡しにくくなります。

## 判断

スキーマ変更は新しい Alembic revision に記録し、コンテナ起動時の migration 実行も Alembic に統一します。既存 revision は書き換えません。インデックスだけの `db/performance_indexes.sql` は明示的な補助として扱い、履歴管理の代替にしません。

## 影響

DB 変更には migration と関連テストが必要です。API 契約を同時に変更する場合は、Pydantic から Zod を再生成し、DB の構造変更と API の型変更を別々の検証対象として確認します。
