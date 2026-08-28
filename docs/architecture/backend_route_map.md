# Backend route map

`app.py` が composition root となり、各 `APIRouter` を登録します。URL の正確な定義は各 Python ファイルの decorator が正本です。この文書は「どこを見ればよいか」を短時間で特定するための機能マップです。

## アプリ直下の共通ルート

| URL | 実装 | 役割 |
| --- | --- | --- |
| `GET /api/csrf-token` | `app.py` | セッション単位の CSRF token 発行 |
| `GET /healthz` | `app.py` → `services/health.py` | プロセスの liveness |
| `GET /readyz` | `app.py` → `services/health.py` | DB と補助依存先を含む readiness |
| MCP well-known routes | `app.py`（MCP 有効時） | OAuth discovery metadata |
| MCP machine routes | `services/mcp_server.py`（MCP 有効時） | `/mcp`、`/authorize`、`/token` 等の MCP ASGI 境界 |

## 機能別 router

| Router | URL の範囲 | 主な実装ファイル | 主な責務 |
| --- | --- | --- | --- |
| `auth_bp` | `/login`, `/register`, `/logout`, `/api/current_user`, `/api/auth/*`, `/api/passkeys/*`, `/google-*` | `blueprints/auth.py`, `auth_account.py`, `auth_email.py`, `auth_google.py`, `auth_passkeys.py` | メール、Google、Passkey 認証とアカウント操作 |
| `verification_bp` | `/api/send_verification_email`, `/api/verify_registration_code` | `blueprints/verification.py` | 登録メール確認コード |
| `chat_bp` | `/`, `/settings`, `/api/*` | `blueprints/chat/{views,rooms,messages,tasks,skills,projects,profile,preferences}.py` | チャット、部屋、SSE、タスク、個人Skill、プロジェクト、プロフィール、設定 |
| `prompt_share_bp` | `/prompt_share/*` | `blueprints/prompt_share/__init__.py` | Next.js のプロンプト共有画面へのリダイレクト |
| `prompt_share_api_bp` | `/prompt_share/api/*` | `blueprints/prompt_share/prompt_share_api.py` | 公開プロンプト、詳細、投稿、コメント、いいね、メディア |
| `search_bp` | `/search/prompts` | `blueprints/prompt_share/prompt_search.py` | 公開プロンプト検索 |
| `prompt_manage_api_bp` | `/prompt_manage/api/*` | `blueprints/prompt_share/prompt_manage_api.py` | 自分の投稿、保存・いいね一覧、編集・削除 |
| `memo_bp` | `/memo/api/*`、`/memo` | `blueprints/memo/routes.py`, `repository.py`, `exports.py` | メモ、コレクション、共有、並び替え、エクスポート |
| `context_vault_bp` | `/api/context-facts/*` | `blueprints/context_vault/routes.py`, `services/context_vault_*` | コンテキスト事実、候補、import/export、抽出設定 |
| `admin_bp` | `/admin/*` | `blueprints/admin/views.py` | 管理ログイン、ダッシュボード、管理用 DB 操作 |
| `mcp_oauth_bp` | `/api/mcp/oauth/*` | `blueprints/mcp_oauth.py`, `services/mcp_oauth.py` | MCP 同意、クライアント、接続の管理 |

## チャット API の流れ

`blueprints/chat/messages.py` のチャット系ルートは、次の役割に分かれています。

1. `POST /api/chat`: 入力・部屋所有者・クォータ・参照コンテキストを検証して生成ジョブを開始。
2. `GET /api/chat_generation_stream`: 生成ジョブのイベントを SSE で配信し、再接続を処理。
3. `GET /api/chat_generation_status`: 再接続前の状態確認。
4. `POST /api/chat_stop`: 生成の停止要求。
5. `POST /api/chat_regenerate`、`/api/chat_edit_and_regenerate`: 既存履歴から分岐生成。
6. `POST /api/chat_switch_branch`: 現在表示する履歴ブランチを切り替え。

ジョブの実行・永続化・Redis 協調は `services/chat_generation.py`、LLM provider の振り分けは `services/llm.py` に置き、ルートへ重複実装しません。

個人Skillは `GET /api/skills` で一覧を取得し、`POST /api/skills` で追加、
`PATCH /api/skills/{skill_id}` で有効状態を切り替え、`DELETE /api/skills/{skill_id}`
で削除します。すべて所有ユーザーに限定され、状態変更は `chat_bp` のCSRF境界を継承します。

## 共通のルート境界

- 状態変更ルートは `require_csrf` を router dependency または既存共通境界から適用します。
- 認証・所有者確認・クォータはルートの入力検証だけで完結させず、サービス／repository 側でも信頼境界を確認します。
- JSON の入出力は `services/request_models.py`、`services/response_models.py`、`services/web.py` の既存パターンを優先します。
- DB 操作は `services/db.py` の接続プールを使います。既存の `blueprints/memo/repository.py` のように機能内 repository がある場合は、移動ではなく境界を確認して変更します。

### ルートを探すコマンド

新しい endpoint の影響範囲を確認するときは、アプリを起動して外部状態を変更する代わりに decorator と router 登録を検索します。

```sh
rg -n '^@[^ ]+\\.(get|post|put|patch|delete|api_route)|APIRouter\\(' blueprints app.py
```
