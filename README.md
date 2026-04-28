> 一番下に日本語版もあります

# ChatCore-AI

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.133+-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14.2+-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-18.3+-61DAFB?logo=react&logoColor=000000)
![TypeScript](https://img.shields.io/badge/TypeScript-5.4+-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-3.4+-06B6D4?logo=tailwindcss&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker%20Compose-Local%20Dev-2496ED?logo=docker&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-LLM%20API-F55036?logo=groq&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-LLM%20API-4285F4?logo=google&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-LLM%20API-412991?logo=openai&logoColor=white)

**🚀 Live Demo: [https://chatcore-ai.com/](https://chatcore-ai.com/)**

## UI Preview

![UI preview](assets/images/chatcore_screenshot.png)

## 🎬 Demo Videos

Click a thumbnail to open the video on YouTube.

<p align="center">
  <a href="https://youtu.be/tdPZJdZfeQ0" target="_blank" rel="noopener noreferrer">
    <img src="https://img.youtube.com/vi/tdPZJdZfeQ0/maxresdefault.jpg" alt="Watch the demo video" width="720">
  </a>
  <br>
  <sub><b>▶ Watch Demo Video</b></sub>
</p>

## Overview
Chat-Core-AI is a FastAPI-based AI chat application with email-based authentication, persistent + ephemeral conversations, and prompt sharing. It integrates with Groq, Google Gemini, and OpenAI APIs, uses PostgreSQL for storage, and ships with a Next.js frontend.

## Key Features
- **Email-based authentication** with 6‑digit verification codes
- **Google OAuth** sign-in
- **Streaming LLM responses** via Server-Sent Events (SSE) — all three providers
- **Persistent + ephemeral chat** modes
- **Chat room sharing** via public URLs and SNS link sharing
- **Prompt sharing** with search and public visibility controls
- **Groq / Gemini / OpenAI** integrations for LLM responses

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Frontend**: Next.js 14, React 18, TypeScript, Tailwind CSS
- **Database / Cache**: PostgreSQL 15, Redis 7 (optional)
- **LLM Providers**: Groq, Google Gemini, OpenAI
- **Local Dev**: Docker Compose

## Quick Start (Docker Compose)
> This project standardizes local execution on Docker Compose.

```sh
# 1) Clone the repository
git clone https://github.com/kota-kawa/ChatCore-AI.git
cd ChatCore-AI

# 2) Create a .env file with required environment variables
cp .env.example .env

# 3) Build and run
docker-compose up --build
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:5004`

## Database Migrations (Alembic)
Schema management is unified on Alembic. `docker-compose up --build` now waits for PostgreSQL and runs `alembic upgrade head` automatically before starting the API. No separate `init.sql` bootstrap is required or used.

For existing environments, you can also apply DB changes manually:

```sh
# Install dependencies first
pip install -r requirements.txt

# Apply all migrations
alembic upgrade head
```

- Default task definitions are centralized in `frontend/data/default_tasks.json` and seeded on startup.
- `alembic/versions/` contains incremental migration history.
- `db/performance_indexes.sql` is kept as a direct SQL fallback for index-only updates.
- API schema single source: backend Pydantic models (`services/request_models.py`, `services/response_models.py`) are converted into frontend Zod schemas at `frontend/types/generated/api_schemas.ts` via `python3 scripts/generate_frontend_zod_schemas.py` (or `npm --prefix frontend run generate:api-schemas`).

## Challenges & Solutions

**Redis session fallback** — Sessions are stored server-side in Redis, but a Redis outage would have invalidated all user sessions. Solved by implementing a hybrid session middleware that automatically falls back to signed cookies when Redis is unavailable or fails mid-request, with no disruption to the user.

**DB connection resilience** — In Docker Compose, the backend container sometimes starts before the database is ready. Solved by having the connection pool try multiple host aliases (`db`, `localhost`, `127.0.0.1`) in sequence, validating each candidate before accepting it.

**LLM cost control** — Exposing LLM endpoints directly risked runaway API costs. Solved by implementing a centralized daily quota counter (shared across all users) that short-circuits requests at the service layer before any external API call is made.

**Testing Redis-dependent code in CI** — The session middleware's Redis fallback behavior requires an actual Redis connection to test, which is not available in standard CI runners. Solved by separating the fallback tests into a quarantined job that runs on a best-effort basis (`continue-on-error: true`) on push to main, keeping the main test gate fast and reliable.

## CI/CD & Testing

**Pipeline** (GitHub Actions — runs on every push and pull request):

| Job | What it checks |
|---|---|
| Ruff Lint | Syntax errors and undefined names (fast gate) |
| Unit Tests | 25+ unit tests covering services, auth, chat, rate limiting, security |
| Integration Tests | Route-level endpoint tests against the full ASGI app |
| Coverage Report | Combined unit + integration coverage, uploaded as XML artifact |
| Frontend Checks | TypeScript type-check and import resolution via `npm run typecheck` |
| Deploy | SSH deploy to production — only runs after all jobs pass on `main` |

- Concurrent runs on the same branch are automatically cancelled to avoid redundant work.
- A scheduled run fires daily at 03:00 UTC to catch dependency regressions.
- Failed deploys trigger an automatic rollback to the previous Git commit.

## Performance & Scalability

- **Connection pooling**: PostgreSQL connections are managed via `psycopg2.ThreadedConnectionPool` with configurable min/max bounds, avoiding per-request connection overhead.
  Set `DB_POOL_MIN_CONN` / `DB_POOL_MAX_CONN` for general environments, and `DB_POOL_MIN_CONN_PRODUCTION` / `DB_POOL_MAX_CONN_PRODUCTION` to override them only when `FASTAPI_ENV=production`.
- **Redis-backed sessions**: When Redis is available, session data is stored server-side, enabling stateless horizontal scaling of the application tier.
- **Rate limiting**: Per-day caps on chat LLM API calls and verification email sends, plus a separate monthly support AI agent cap, are enforced at the service layer to protect external API quotas and infrastructure cost.
- **Health endpoints**: `GET /healthz` returns process liveness; `GET /readyz` checks live DB reachability and reports Redis as degraded-but-optional, enabling load balancer health checks without false negatives.
- **Structured logging**: All requests emit JSON logs with `X-Request-ID` correlation IDs, making distributed tracing and incident diagnosis tractable at scale.

## Project Structure
- `app.py`: FastAPI entry point
- `blueprints/`: feature modules (auth, chat, memo, prompt_share, admin)
- `services/`: shared integrations (DB, LLM, email, user helpers)
- `templates/` and `static/`: global HTML/CSS/JS assets
- `alembic/versions/`: PostgreSQL schema migration history
- `frontend/`: Next.js frontend

## Architecture Diagram
```mermaid
flowchart LR
    U[User Browser]
    FE[Next.js Frontend]
    API[FastAPI Backend]
    BP[Blueprints<br/>auth/chat/memo/prompt_share/admin]
    SV[Services<br/>db/llm/email/user]
    DB[(PostgreSQL)]
    RD[(Redis Optional)]
    LLM[Groq / Gemini APIs]
    EM[Email Provider]

    U --> FE --> API
    API --> BP --> SV
    SV --> DB
    SV --> RD
    SV --> LLM
    SV --> EM
```

## Design Decisions
- **Why FastAPI (instead of Flask)**: FastAPI gives async-first request handling, type-driven validation, and automatic OpenAPI docs. This reduces API integration friction and keeps backend contracts explicit.  
  Trade-off: stricter typing and async patterns add some implementation complexity.
- **Why Redis for session/state (optional)**: When Redis is available, sessions are stored server-side and shared across instances, which improves horizontal scalability and supports operational controls (e.g., centralized invalidation, quota/ephemeral state handling).  
  Trade-off: extra infrastructure and operational overhead.
- **Why PostgreSQL as the primary datastore**: Core entities (users, chats, prompts, admin data) are relational and consistency-sensitive. PostgreSQL provides strong integrity guarantees plus mature indexing/migration workflows.
- **Why Next.js for frontend**: Next.js supports route-based UI composition and production-ready optimization while allowing incremental migration from legacy static/script assets.
- **Why backend-driven API schemas**: Request/response contracts are authored once in backend Pydantic models and generated into frontend Zod schemas. This removes manual double maintenance and prevents backend/frontend contract drift.

## Engineering Highlights (for reviewers)
- **Hybrid session middleware** (`services/session_middleware.py`): Built a custom ASGI middleware that transparently falls back from Redis-backed sessions to signed-cookie sessions when Redis is unavailable or fails mid-request — no session loss, no user disruption. Also implements session fixation prevention by rotating the session identifier on login.
- **Streaming LLM responses** (`services/chat_generation.py`): LLM responses are streamed token-by-token via SSE using a background `ChatGenerationJob` thread. Jobs are cancellable, and the completed response is persisted to the database only after the full stream finishes, keeping the HTTP handler thin.
- **Provider-agnostic LLM abstraction** (`services/llm.py`): A single `get_llm_response` / `get_llm_response_stream` interface routes to Groq, Gemini, or OpenAI based on model name, with an allowlist that rejects unsupported models before any external call is made.
- **LLM input sanitization**: Conversation messages are scanned for known secret patterns (API keys, OAuth tokens, passwords) using compiled regexes and redacted before forwarding to any LLM provider, preventing accidental secret leakage.
- **CSRF protection** (`services/csrf.py`): Custom header-based CSRF token validation is enforced on all state-changing requests. Tokens are auto-generated per session inside the session middleware, requiring no extra setup per route.

## License
Copyright (c) 2026 Kota Kawagoe

Licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.

---

<details>
<summary>日本語版 (クリックして展開)</summary>

# Chat-Core-AI

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.133+-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14.2+-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-18.3+-61DAFB?logo=react&logoColor=000000)
![TypeScript](https://img.shields.io/badge/TypeScript-5.4+-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-3.4+-06B6D4?logo=tailwindcss&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker%20Compose-Local%20Dev-2496ED?logo=docker&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-LLM%20API-F55036?logo=groq&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-LLM%20API-4285F4?logo=google&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-LLM%20API-412991?logo=openai&logoColor=white)

**🚀 ライブデモ: [https://chatcore-ai.com/](https://chatcore-ai.com/)**

## UI Preview

![UI preview](assets/images/chatcore_screenshot.png)

## 🎬 Demo Videos

Click a thumbnail to open the video on YouTube.

<p align="center">
  <a href="https://youtu.be/tdPZJdZfeQ0" target="_blank" rel="noopener noreferrer">
    <img src="https://img.youtube.com/vi/tdPZJdZfeQ0/maxresdefault.jpg" alt="デモ動画を見る" width="720">
  </a>
  <br>
  <sub><b>▶ デモ動画を見る</b></sub>
</p>

## 概要
Chat-Core-AI は FastAPI で構築した AI チャットアプリです。メール認証・永続／エフェメラルチャット・プロンプト共有を備え、Groq・Google Gemini・OpenAI API に対応しています。PostgreSQL を採用し、Next.js フロントエンドと連携します。

## 主な機能
- **メール認証**（6 桁コード）
- **Google OAuth** ログイン
- **LLM ストリーミング応答**（SSE 経由 — 全プロバイダ対応）
- **永続／エフェメラル**のチャット
- **チャット共有リンク**（URL/SNS 共有）
- **プロンプト共有**（公開・検索）
- **Groq / Gemini / OpenAI 連携**

## 技術スタック
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Frontend**: Next.js 14, React 18, TypeScript, Tailwind CSS
- **Database / Cache**: PostgreSQL 15, Redis 7（任意）
- **LLM Providers**: Groq, Google Gemini, OpenAI
- **Local Dev**: Docker Compose

## 実行方法（Docker Compose）
> 実行方法は Docker Compose に統一しています。

```sh
# 1) リポジトリを取得
git clone https://github.com/kota-kawa/ChatCore-AI.git
cd ChatCore-AI

# 2) 環境変数を設定
cp .env.example .env

# 3) ビルド＆起動
docker-compose up --build
```

- フロントエンド: `http://localhost:3000`
- API: `http://localhost:5004`

## データベースマイグレーション（Alembic）
スキーマ管理は Alembic に統一しています。`docker-compose up --build` では PostgreSQL の起動待ち後に `alembic upgrade head` を実行してから API を起動します。`init.sql` のような別系統の初期化スクリプトは使いません。

既存環境へ手動で適用する場合は次を実行してください。

```sh
# 先に依存関係をインストール
pip install -r requirements.txt

# 全マイグレーションを適用
alembic upgrade head
```

- 既定タスク定義は `frontend/data/default_tasks.json` を単一ソースとして起動時に投入
- `alembic/versions/`: 段階的な変更履歴
- `db/performance_indexes.sql`: インデックスのみを直接適用するフォールバックSQL
- APIスキーマの単一ソース: バックエンドPydantic（`services/request_models.py`, `services/response_models.py`）を `python3 scripts/generate_frontend_zod_schemas.py`（または `npm --prefix frontend run generate:api-schemas`）でフロントエンドZod（`frontend/types/generated/api_schemas.ts`）へ生成

## 課題と解決策（Challenges & Solutions）

**Redisセッションのフォールバック** — セッションをRedisにサーバー側保存する設計では、Redis障害時に全ユーザーのセッションが失われるリスクがありました。ハイブリッドセッションミドルウェアを実装し、RedisがダウンまたはリクエストM中にエラーが発生した場合は署名付きCookieへ自動フォールバックすることで、ユーザーへの影響ゼロで障害を吸収しています。

**DBコネクションの耐障害性** — Docker ComposeではバックエンドコンテナがDBより先に起動してしまうことがありました。コネクションプールが `db`・`localhost`・`127.0.0.1` など複数ホストを順番に試し、接続確認が取れた最初のホストを採用する設計で解決しています。

**LLMコスト制御** — LLMエンドポイントを直接公開すると外部API費用が青天井になるリスクがあります。全ユーザー合算の日次クォータカウンターをサービス層で一元管理し、外部API呼び出しの前段階でリクエストを遮断することで対処しています。

**CI環境でのRedis依存テスト** — セッションのフォールバック挙動は実際のRedis接続が必要なため、通常のCIランナーではテストできません。フォールバックテストを独立した `continue-on-error: true` のジョブに隔離し、mainへのpush時のみベストエフォートで実行することで、メインのテストゲートを高速かつ信頼性の高い状態に保っています。

## CI/CDとテスト（CI/CD & Testing）

**パイプライン**（GitHub Actions — 全push・PRで実行）:

| ジョブ | 確認内容 |
|---|---|
| Ruff Lint | 構文エラー・未定義名の即時検出（高速ゲート） |
| Unit Tests | サービス層・認証・チャット・レート制限・セキュリティなど25件以上 |
| Integration Tests | 実際のASGIアプリに対するルートレベルのエンドポイントテスト |
| Coverage Report | ユニット＋統合テストの合算カバレッジをXMLアーティファクトとして保存 |
| Frontend Checks | TypeScript型チェックおよびimport解決の検証 |
| Deploy | 全ジョブ通過後にSSHで本番デプロイ（mainのpush時のみ） |

- 同一ブランチで並走するジョブは自動キャンセルして無駄な実行を排除。
- 毎日03:00 UTCにスケジュール実行し、依存パッケージの非互換を継続的に検知。
- デプロイ失敗時は直前のGitコミットへ自動ロールバック。

## パフォーマンスとスケーラビリティ（Performance & Scalability）

- **コネクションプール**: PostgreSQL接続を `psycopg2.ThreadedConnectionPool` で管理し、リクエストごとの接続確立コストを排除。プールサイズは環境変数で調整可能で、`FASTAPI_ENV=production` では `DB_POOL_MIN_CONN_PRODUCTION` / `DB_POOL_MAX_CONN_PRODUCTION` で本番向けに上書きできます。
- **Redisセッション**: Redis利用時はセッションデータをサーバー側に保存。アプリ層をステートレスに保ち、水平スケールを容易にする設計。
- **レート制限**: LLM API呼び出し・認証メール送信の日次上限に加え、ゲストチャット回数制限（`GUEST_CHAT_DAILY_LIMIT`）もサービス層のサーバー側カウンタで一元管理し、Cookie改ざんによる回避や外部APIコスト増大を防止。
- **ヘルスエンドポイント**: `GET /healthz` でプロセス生存確認、`GET /readyz` でDB到達性とRedis劣化状態を返し、ロードバランサーのヘルスチェックに対応。
- **構造化ログ**: 全リクエストに `X-Request-ID` 相関IDを付与したJSONログを出力し、障害時のトレーサビリティを確保。

## ディレクトリ構成
- `app.py`: FastAPI エントリーポイント
- `blueprints/`: 機能別モジュール（auth, chat, memo, prompt_share, admin）
- `services/`: DB/LLM/メールなど共通処理
- `templates/`・`static/`: 共有 HTML/CSS/JS
- `alembic/versions/`: PostgreSQL スキーマ変更履歴
- `frontend/`: Next.js フロントエンド

## アーキテクチャ図
```mermaid
flowchart LR
    U[ユーザーブラウザ]
    FE[Next.js フロントエンド]
    API[FastAPI バックエンド]
    BP[Blueprints<br/>auth/chat/memo/prompt_share/admin]
    SV[Services<br/>db/llm/email/user]
    DB[(PostgreSQL)]
    RD[(Redis 任意)]
    LLM[Groq / Gemini API]
    EM[メールプロバイダ]

    U --> FE --> API
    API --> BP --> SV
    SV --> DB
    SV --> RD
    SV --> LLM
    SV --> EM
```

## 技術的な意思決定（Design Decisions）
- **なぜ FastAPI（Flask ではなく）を選んだか**: 非同期処理、型ヒントベースのバリデーション、自動生成される OpenAPI ドキュメントを活用し、API 連携と仕様の明確化を優先したためです。  
  トレードオフ: 型定義と async の実装負荷は増えます。
- **なぜ Redis をセッション/状態管理に使うか（任意）**: Redis 利用時はセッションをサーバー側で一元管理でき、複数インスタンス構成でも共有しやすく、失効制御やクォータ/エフェメラル状態の運用がしやすくなります。  
  トレードオフ: 追加インフラの運用コストが発生します。
- **なぜ PostgreSQL を主データストアにしたか**: ユーザー・チャット・プロンプト・管理データは関係性と整合性が重要なため、整合性保証・インデックス・マイグレーションが成熟した PostgreSQL を採用しています。
- **なぜ Next.js を採用したか**: ルート単位でUIを構成しつつ本番最適化を行え、既存の静的アセット/スクリプト構成から段階的に移行しやすいためです。
- **なぜ API スキーマをバックエンド主導にしたか**: リクエスト/レスポンス契約をバックエンドPydanticに集約し、フロントエンドZodは生成で同期します。手書き二重管理をなくし、契約ドリフトを防ぐためです。

## レビュー観点の強み
- **ハイブリッドセッションミドルウェア** (`services/session_middleware.py`): Redis バックエンドから署名付き Cookie への透過的フォールバックを実装したカスタム ASGI ミドルウェア。Redis 障害時もセッション消失なし・ユーザー影響ゼロで吸収。ログイン時のセッション ID 再発行によるセッション固定攻撃対策も実装。
- **LLM ストリーミング応答** (`services/chat_generation.py`): バックグラウンドスレッド上の `ChatGenerationJob` がトークン逐次生成し SSE で配信。ジョブはキャンセル可能で、レスポンス全体の受信完了後にのみ DB 保存を行うことで HTTP ハンドラを薄く保つ設計。
- **プロバイダ非依存 LLM 抽象層** (`services/llm.py`): `get_llm_response` / `get_llm_response_stream` の単一インターフェースがモデル名でルーティング。許可リスト外のモデルは外部 API 呼び出し前に即時拒否。
- **LLM 入力サニタイズ**: API キー・OAuth トークン・パスワードなどの秘密情報パターンをコンパイル済み正規表現でスキャンし、外部 LLM プロバイダへ送信する前に自動的に伏せ字化。意図しない秘密漏洩を防止。
- **CSRF 対策** (`services/csrf.py`): ヘッダーベースの CSRF トークン検証をすべての状態変更リクエストに適用。トークンはセッションミドルウェア内でセッションごとに自動生成されるため、ルートごとの追加設定不要。

## ライセンス
Copyright (c) 2026 Kota Kawagoe

Apache License, Version 2.0 の下でライセンスされています。詳細は [LICENSE](LICENSE) を参照してください。

</details>
