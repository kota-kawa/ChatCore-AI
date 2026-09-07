# ADR 0004: DB スキーマ変更を Alembic の履歴で管理する

- 状態: Accepted
- 対象: `alembic/`, `alembic/versions/`, `docker/app-entrypoint.sh`

## 背景

複数環境でアプリケーションと PostgreSQL の構造を一致させるには、起動時に暗黙の SQL を実行する方式では適用順序と適用済み状態を追跡しにくくなります。

## 判断

スキーマ変更は新しい Alembic revision に記録し、コンテナ起動時の migration 実行も Alembic に統一します。既存 revision は書き換えません。インデックスだけの `db/performance_indexes.sql` は明示的な補助として扱い、履歴管理の代替にしません。

## 影響

DB 変更には migration と関連テストが必要です。API 契約を同時に変更する場合は、Pydantic から Zod を再生成し、DB の構造変更と API の型変更を別々の検証対象として確認します。

## 更新履歴

### 2026-09-07: インデックス用 SQL フォールバックの削除

`db/performance_indexes.sql` を削除しました。同ファイルが定義していた 16 個のインデックスはすべて `alembic/versions/` の revision（主に `20260227_01_db_index_and_search_improvements.py`）で作成済みで、ファイル自体はどのコード・起動スクリプトからも実行されておらず、散文からのみ参照されていました。さらに 2 件は head のスキーマと矛盾していました（`idx_prompts_public_category_trgm` は `20260709_01_task_oriented_prompt_categories.py` で意図的に削除済み、`idx_prompt_list_user_created_at` の対象テーブル `prompt_list_entries` は `20260618_01_drop_prompt_bookmarks.py` で削除済み）。この二重管理は本 ADR の判断そのものに反するため、補助ファイルという位置づけを取り下げ、インデックスも含めたスキーマの正本を Alembic 履歴だけに統一します。上記「判断」の記述は当時の判断として残し、本節で上書きします。
