# Chat-Core-AI 内部アーキテクチャ

この文書は、Codex が変更箇所を特定するための内部設計の正本です。公開向けの概要・起動手順は `README.md`、利用者向けの操作説明は `docs/manual/`、CSS の詳細は `frontend/STYLING_STRATEGY.md` を参照してください。

## 1. システムの境界

ブラウザから利用する Next.js アプリと、FastAPI が提供する API・認証・バックグラウンド処理で構成されます。永続データは PostgreSQL、セッション・キャッシュ・ワーカー間の協調には設定時の Redis を使います。LLM、メール、OAuth、MCP は外部境界です。

```mermaid
flowchart LR
    B[Browser]
    FE[frontend/\nNext.js pages/components/hooks]
    API[app.py\nFastAPI]
    MW[Middleware\nsession / CSRF / request context / security]
    BP[blueprints/\nHTTP routes]
    SV[services/\nuse cases and integrations]
    REPO[repositories\nshared data access]
    PG[(PostgreSQL)]
    RD[(Redis\noptional by configuration)]
    LLM[LLM providers]
    EXT[Email / OAuth / MCP]

    B --> FE --> API --> MW --> BP --> SV
    SV --> REPO --> PG
    SV --> PG
    SV --> RD
    SV --> LLM
    SV --> EXT
```

### 正本と補助資料

| 情報 | 正本 | 変更時の参照先 |
| --- | --- | --- |
| HTTP のリクエスト／レスポンスモデル | `services/request_models.py`, `services/response_models.py` | `docs/knowledge/contracts-and-migrations.md` |
| フロントエンド用の生成済み契約 | `frontend/types/generated/api_schemas.ts`（生成物） | `scripts/generate_frontend_zod_schemas.py` |
| DB スキーマの変更履歴 | `alembic/versions/` | `docs/knowledge/contracts-and-migrations.md` |
| プロンプト添付画像の処理・保存境界 | `services/prompt_attachment_processing.py`, `services/prompt_attachment_storage.py` | `docs/architecture/prompt_attachment_storage.md` |
| フロントエンドの CSS 規約 | `frontend/STYLING_STRATEGY.md` と `frontend/public/static/css/` | UI 変更時に同文書を確認 |
| 技術判断の理由 | `docs/decisions/` | 既存 ADR を更新または新規 ADR を追加 |

### 構造の詳細マップ

全体像を確認した後、必要な領域だけ次の文書を開きます。

- [Frontend feature map](docs/architecture/frontend_feature_map.md): ページ、主要コンポーネント、hook、API 呼び出しの対応。
- [Backend route map](docs/architecture/backend_route_map.md): `app.py` が登録する router、URL 接頭辞、機能別ハンドラの対応。
- [Data model](docs/architecture/data_model.md): PostgreSQL の主要エンティティ、関連、Redis／ファイル保存との境界。
- [Deployment and operations](docs/architecture/deployment_and_operations.md): Docker Compose、Blue/Green、起動順、ポート、ボリューム、healthcheck。
- [Testing map](docs/architecture/testing_map.md): Backend／Frontend のテスト配置と機能別の選び方。
- [Prompt attachment storage](docs/architecture/prompt_attachment_storage.md): 添付画像処理と保存契約の詳細。

## 2. バックエンドの起動と構成

### `app.py` の責務

`app.py` はアプリケーションの composition root です。機能ロジックを追加する場所ではありません。主な起動順序は次のとおりです。

1. 環境設定を読み込み、ロギングを設定し、セッション署名キーを検証する。
2. `FastAPI` インスタンスと、認証制限・LLM 日次制限・チャット生成サービスを `app.state` に登録する。
3. セッション、ロケール、リクエストコンテキスト、セキュリティヘッダー、リクエストサイズ制限のミドルウェアを登録する。
4. `blueprints/` の各 `APIRouter` を登録する。
5. lifespan で初期データのシード、エフェメラルデータ／添付ファイルの定期クリーンアップ、MCP のライフサイクル、終了時のジョブ・DB プール停止を管理する。

ヘルスチェックは `GET /healthz`（プロセスの生存）と `GET /readyz`（依存先を含む準備状態）で分かれています。デバッグ時にこの二つを同じ意味として扱わないでください。

### レイヤーの責務

- `blueprints/`: HTTP のルート、認証・CSRF の境界、入力の受け取り、レスポンスへの変換を担当します。チャット、プロンプト共有、メモ、コンテキスト金庫、管理、認証を機能単位に分割しています。
- `services/`: 複数のルートから使う業務処理、外部連携、共通エラー、セキュリティ、キャッシュ、バックグラウンド処理を担当します。ルートから直接呼ぶ必要がある場合も、処理をサービスへ寄せてハンドラを薄く保ちます。
- `services/repositories/`: 複数機能で共有する DB アクセスの配置先です。既存コードには機能配下のデータアクセス（例: `blueprints/memo/repository.py`）もあるため、移動を目的にした大規模リファクタリングは行わず、新規の共有アクセスからこの境界を優先します。
- `services/request_models.py` / `services/response_models.py`: API 契約を定義します。フロントエンドの型を手書きで先行変更しないでください。
- `services/api_errors.py` / `services/error_messages.py`: API エラーの型と利用者向け文言を集約します。
- `services/csrf.py`: 状態変更リクエストに対する CSRF 検証の共通境界です。ルートごとに独自実装を増やしません。

### ルーターの主な対応表

| パッケージ | 主な範囲 | 代表的な URL の接頭辞 |
| --- | --- | --- |
| `blueprints/auth*.py`, `verification.py`, `auth_passkeys.py` | メール・Google・Passkey 認証 | `/api/auth`, `/oauth`, `/api/passkeys` |
| `blueprints/chat/` | チャット、部屋、タスク、プロフィール、設定、プロジェクト | `/api` |
| `blueprints/prompt_share/` | 公開プロンプト、検索、管理、メディア | `/prompt_share`, `/prompt_manage`, `/search` |
| `blueprints/memo/` | メモ、コレクション、共有、エクスポート | `/memo` |
| `blueprints/context_vault/` | パーソナル・コンテキストと候補の承認 | `/api/context-facts` |
| `blueprints/admin/` | 管理画面と管理 API | `/admin` |
| `blueprints/mcp_oauth.py` | MCP OAuth クライアント・接続管理 | `/api/mcp/oauth` |

状態を変更するルートは既存ルーターの依存関係と同様に CSRF を適用し、認証・所有者確認・レート制限をルートまたはサービスの適切な境界で行います。

## 3. データ、セッション、外部連携

### PostgreSQL とマイグレーション

`services/db.py` は `psycopg2` の `ThreadedConnectionPool` を包み、接続の検証、ホスト候補の切り替え、接続取得の有限リトライ、返却前のロールバックを提供します。アプリケーションの通常の DB 操作はこの接続境界を利用します。SQLAlchemy のモデル層を前提にして実装箇所を探さないでください。

スキーマ変更は Alembic の新しい revision として追加します。適用済み revision の書き換えや、アプリ起動時だけの暗黙の ALTER は行いません。インデックスだけの直接 SQL フォールバックとして `db/performance_indexes.sql` が存在しますが、通常のスキーマ履歴の代替ではありません。

### Redis の役割

Redis は設定されている環境で次の用途に使われます。

- セッション本体（`session:<id>`）の保存。ブラウザ Cookie には署名された Redis 参照 ID だけを保持します。
- キャッシュ、日次・月次制限、シングルフライトロック。
- 複数ワーカーをまたぐチャット生成イベント、停止通知、再接続用の協調。

Redis 障害時の扱いは用途ごとに異なります。一般キャッシュの未ヒットやシングルフライトのフェイルオープンは可能ですが、セッション本体は機密値を Cookie に書き込むフォールバックを行いません。保存に失敗した場合は Cookie を消去し、必要に応じて再認証させます。ログイン ID は認証成功時にローテーションされます。

### チャット生成と SSE

チャットの生成は HTTP ハンドラ内で LLM 呼び出しを完了させるのではなく、`services/chat_generation.py` の `ChatGenerationService`／`ChatGenerationJob` に委譲します。

1. `blueprints/chat/messages.py` が入力、部屋の所有権、制限、参照コンテキストを検証してジョブを開始する。
2. バックグラウンド実行器上のジョブが `services/llm.py` のプロバイダ抽象化を通じてストリームを読む。
3. ジョブはイベントに連番を付け、接続中の SSE に通知し、必要に応じて Redis のリプレイ／協調機能を使う。
4. フロントエンドは `/api/chat_generation_stream` などの SSE エンドポイントを購読し、切断時はステータス確認と再接続を行う。
5. 応答の永続化はジョブの終了・停止経路で一度だけ行います。途中停止でも生成済みの本文を扱うため、完了と停止の二重保存を追加しないでください。

`frontend/lib/chat_page/api_contract.ts` は、レガシー応答や生成 UI パーツを画面で安全に扱うための正規化層です。API の構造を変更する場合は、バックエンドモデル、生成スキーマ、必要な正規化処理を同時に確認します。

### 添付ファイル

プロンプト共有の画像は、処理（デコード、ピクセル数・アニメーション制限、EXIF 向き、メタデータ除去）と保存先を分離しています。保存契約や将来のオブジェクトストレージ移行条件は `docs/architecture/prompt_attachment_storage.md` に集約されています。この文書へ詳細を複製しません。

## 4. フロントエンドの構成

- `frontend/pages/`: Next.js Pages Router のページエントリーポイント。ページ単位のデータ取得と画面構成を担当します。
- `frontend/components/`: 機能単位・共通 UI の React コンポーネント。チャット、メモ、プロンプト共有、設定、認証などに分かれています。
- `frontend/hooks/` と `frontend/contexts/`: 複数コンポーネントで共有する状態・副作用・画面フローを担当します。チャットページの巨大なフローは用途別 hook に分割されています。
- `frontend/lib/`: API 呼び出し、SWR、レスポンス正規化、i18n、ストリーム処理などの再利用ロジックです。読み取りは `swrFetcher`、一般リクエストは `resilientFetch` の既存パターンを優先します。
- `frontend/scripts/`: ブラウザ側の共通ランタイム（CSRF、テーマ、再試行付き fetch など）です。
- `frontend/public/` と `frontend/styles/`: 静的 CSS、ページ・コンポーネント用 CSS、互換スタイルを配置します。トークンと CSS の責務分割は `frontend/STYLING_STRATEGY.md` が正本です。
- `frontend/types/generated/api_schemas.ts`: バックエンド Pydantic モデルから生成されるファイルです。直接編集しません。

### API 契約の同期

バックエンドの request/response model を変更したら、リポジトリルートまたは `frontend/` から次を実行して生成物を更新します。

```sh
npm --prefix frontend run generate:api-schemas
```

生成後は変更範囲に応じて `npm --prefix frontend run typecheck` と対象テストを実行します。詳細な失敗パターンは `docs/knowledge/contracts-and-migrations.md` にあります。

## 5. 変更時のナビゲーション

| 変更したいもの | 最初に見る場所 | 併せて確認するもの |
| --- | --- | --- |
| API の入出力 | 対応する `blueprints/` と `services/*_models.py` | 生成 Zod、フロントの API 正規化、ルートテスト |
| チャットの生成・停止・再接続 | `services/chat_generation.py` | `blueprints/chat/messages.py`、`frontend/hooks/chat_page/`、SSE テスト |
| 認証・セッション・CSRF | `blueprints/auth*`、`services/session_middleware.py`、`services/csrf.py` | Redis の設定、セキュリティテスト、ログイン後の ID ローテーション |
| 永続データ | 対応サービス／リポジトリ | 新規 Alembic revision、所有者確認、対象 DB テスト |
| プロンプト画像 | `services/prompt_attachment_processing.py` と storage | `docs/architecture/prompt_attachment_storage.md`、添付テスト |
| UI と CSS | 対応 `pages/`・`components/` | `frontend/STYLING_STRATEGY.md`、typecheck、対象 component test |
| 既知の障害やデバッグ | — | `docs/knowledge/debugging.md` |
| 技術判断の変更 | — | `docs/decisions/README.md` と該当 ADR |

変更を始める前に、依存する契約と永続化境界を特定し、関係ないレイヤーの整理を同じ変更に混ぜないでください。
