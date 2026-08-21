# Testing map

テストは実装レイヤーではなく、変更した契約・境界・機能に合わせて絞ります。外部 LLM、メール、DB、Redis は原則モックし、FastAPI の route behavior は integration／route test で確認します。

## Backend

| 変更対象 | 主なテスト群 | 確認内容 |
| --- | --- | --- |
| 認証・セッション・CSRF | `tests/unit/test_auth_*.py`, `test_session_middleware.py`, `test_csrf_protection.py`, `tests/integration/test_session_resilience.py` | 認証状態、ID rotation、Redis 障害、安全な Cookie 処理、CSRF |
| チャット・SSE・部屋 | `tests/unit/test_chat_*.py`, `test_chat_streaming.py`, `test_chat_generation_stop.py`, `tests/integration/test_endpoint_routes.py` | 入力、所有者、branch、quota、生成イベント、停止・再接続 |
| タスク・prompt assist | `test_default_tasks.py`, `test_edit_default_task.py`, `test_task_*.py`, `test_prompt_assist*.py` | seed、localized task、並び順、重複制約、assist quota |
| Prompt sharing | `test_prompt_share*.py`, `test_prompt_*_api.py`, `test_prompt_attachment_*.py`, `test_prompt_resource_repository.py` | 公開範囲、検索、like/comment、添付処理、resource |
| Memo | `test_memo_*.py`, `test_embedding*.py` | CRUD、collection、archive/pin、share、embedding |
| Context vault | `test_context_vault_*.py`, `test_context_fact_*.py`, `tests/integration/test_context_vault_endpoints.py` | candidate、承認、portability、pagination、API 境界 |
| MCP | `test_mcp_*.py`, `test_mcp_oauth*.py` | OAuth、scope、tool authorization、machine session bypass |
| DB／migration | `test_db_postgres.py`, `test_migration_sql_syntax.py`, migration 名に対応する `test_*_migration.py` | SQL、安全な retry、upgrade/downgrade、制約・index |

## Frontend

- logic test は `frontend/tests/*.test.ts`、component test は `*.component.test.tsx` です。
- チャット変更では `generation_*`、`stream*`、`message_*`、`home_page_*`、`stop_generation` の対象を優先します。
- Prompt sharing 変更では `prompt_share_*`、`prompt_*`、`skill_*` を優先します。
- Memo／Context 変更では `memo_*`、`context_*`、`my_context_panel` を優先します。
- 認証／設定変更では `auth_*`、`locale_*`、`settings_*`、`mcp_oauth_*` を確認します。

## 実行コマンド

```sh
# Backend: 変更に直接関係するものだけ
python3 -m unittest tests.unit.test_chat_streaming
python3 -m unittest tests.integration.test_context_vault_endpoints

# Frontend
npm --prefix frontend run check:imports
npm --prefix frontend run typecheck
npm --prefix frontend run test:logic
npm --prefix frontend run test:components -- tests/prompt_share_api.test.ts
```

API model を変更した場合は、テスト前に `npm --prefix frontend run generate:api-schemas` を実行します。CSS だけの変更では typecheck を必須とせず、直接影響する style／component test を優先します。

## テスト一覧を更新しない方針

この文書は全テストファイルの静的コピーではありません。新しいテストの正確な一覧は `find tests frontend/tests`、機能ごとの実装場所は `ARCHITECTURE.md` と各 feature map を使います。テスト命名規則や対象範囲が変わったときだけこの文書を更新します。
