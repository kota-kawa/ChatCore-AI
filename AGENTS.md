# リポジトリガイドライン

## プロジェクト構成とモジュール構成
- `app.py` はメインサーバーの FastAPI エントリーポイントです。
- `blueprints/` には機能モジュール（auth、chat、memo、prompt_share、admin）と、それぞれのルーティング、テンプレート、静的アセットが含まれています。
- `services/` には、共通のインテグレーション（DB、LLM、メール、ユーザーヘルパー）が格納されています。DB アクセスは可能な限り `services/repositories/`（`chat_repository.py` など）のリポジトリ経由に寄せてください。
- `frontend/` は独立した Next.js アプリ（`strike-frontend`）です。`components/`、`hooks/`、`contexts/`、`lib/` などで構成され、スタイル方針は `frontend/STYLING_STRATEGY.md` を参照してください。バックエンドの API とやり取りする UI はここに実装します。
- `templates/` および `static/` はグローバルな HTML/CSS/JS アセットです。ブループリント固有のアセットは、各ブループリントの `templates/` および `static/` フォルダ配下にあります。
- `alembic/versions/` には PostgreSQL のスキーマ移行履歴が保存されています。
- `tests/` には `unit/` および `integration/` スイート（`unittest`）と、`tests/helpers/` 配下の共通ヘルパーが含まれています。

## ビルド、テスト、開発コマンド
> **注意:** この環境には `python` コマンドがありません。Python コマンドはすべて `python3`（および `python3 -m pip`）を使用してください。
- `docker-compose up --build` は、Docker を使用してフルスタック（FastAPI + PostgreSQL）をビルドし、実行します。
- `python3 -m pip install -r requirements.txt` は、ローカル開発用の Python 依存関係をインストールします。
- `python3 app.py` は、FastAPI アプリをローカルで起動します（必要な環境変数が設定されていることを確認してください）。
- `python3 -m unittest` はテストスイートを実行します。特定のファイルをターゲットにする場合は、`python3 -m unittest tests.unit.test_edit_default_task` のように実行します。
- フロントエンド（`frontend/`）は Node のコマンドを使用します。`npm run dev`（開発サーバー）、`npm run build`（ビルド）、`npm run typecheck`（型検査）、`npm run test`（ロジック + コンポーネントテスト）を実行してください。フロントエンドを変更したら、少なくとも `typecheck` と `test` を通してください。
- 依存バージョンは完全固定（`==` および固定タグ）が必須です。`python3 scripts/check_version_locks.py` で requirements とロック、Docker イメージ、npm スペックの固定を検証できます。浮動バージョン（`^`、`~`、`latest` など）は追加しないでください。

## バックエンド ↔ フロントエンドのスキーマ同期
- API のリクエスト/レスポンスモデル（`services/request_models.py` などの Pydantic モデル）を変更したら、`frontend/` で `npm run generate:api-schemas`（内部で `python3 scripts/generate_frontend_zod_schemas.py` を実行）を走らせて Zod スキーマを再生成してください。
- 生成物 `frontend/types/generated/api_schemas.ts` は自動生成ファイル（`AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.`）です。手で編集せず、必ず生成コマンドで更新してください。
- モデル変更時にスキーマ再生成を忘れると、フロントとバックエンドの型がずれて実行時エラーの原因になります。PR には再生成済みの差分を含めてください。

## 共通ユーティリティと実装規約
- エラー処理: アドホックな例外ではなく `services/api_errors.py`（`ApiServiceError`、`ResourceNotFoundError`、`ForbiddenOperationError` など）を使用し、ユーザー向け文言は `services/error_messages.py` の定数へ集約してください。
- ロギング: `print` ではなく `logging.getLogger(__name__)` を使用します。ロガー設定は `services/logging_config.py`（`configure_logging()`）が担うため、モジュール側で `basicConfig` を呼ばないでください。
- CSRF: 状態を変更するルート（POST/PUT/DELETE など）には、既存の blueprint と同様に CSRF 保護を必ず適用してください。

## コーディングスタイルと命名規則
- Python: 4スペースのインデント、関数や変数には `snake_case`、クラスには `CapWords` を使用します。
- JavaScript: `static/js/` にある既存のモジュールパターンに従い、ファイルを単一責任に保ちます。
- CSS: フロントエンド（Next.js）のスタイルは `frontend/public/static/css/` 配下にあり、`frontend/pages/_app.tsx` から import します（リポジトリ直下に `static/css/` は存在しません）。ベーススタイルは `frontend/public/static/css/base/` に、再利用可能なコンポーネントは `frontend/public/static/css/components/` に、ページの各エントリーポイントは `frontend/public/static/css/pages/<page>/` に配置します。ブループリント固有のスタイルは `frontend/public/<blueprint>/static/css/`（例: `frontend/public/prompt_share/static/css/`）に置きます。BEM スタイルの `kebab-case` クラス名を推奨します。
- フォーマッターは強制されません。変更は周囲のコードと整合性を保つようにしてください。

## 責務分割とファイル肥大化の防止
- 1つのファイル・関数・クラスに責務を詰め込みすぎないでください。単一責任の原則（SRP）を守り、役割が増えてきたら早めにモジュールへ分割します。
- 既存ファイルに機能を追加する際は、そのファイルの責務が肥大化しないか確認してください。関心事が異なる処理は、`services/`（共通ロジック）やブループリント配下の適切なモジュールへ切り出します。
- 関数が長くなりすぎた場合（目安として1画面に収まらない、複数の責務を持つ）は、意味のある単位に分割します。深いネストは早期リターンやヘルパー関数で平坦化してください。
- JavaScript は `static/js/` の既存モジュールパターンに従い、ファイルを単一責任に保ちます。CSS はベース／コンポーネント／ページの区分（`frontend/public/static/css/{base,components,pages}/`）を維持し、1ファイルに無関係なスタイルを混在させないでください。
- テンプレートやルーティングに複雑なロジックを埋め込まず、ビジネスロジックは `services/` へ寄せ、各レイヤーの責務を明確に保ちます。
- 既存の重複や肥大化に気づいた場合でも、依頼された変更の範囲を大きく超えるリファクタリングは避け、必要に応じて PR やコメントで分割を提案してください。

## テストガイドライン
- フレームワーク: `unittest` （`tests/unit/test_edit_default_task.py` を参照）。
- 命名: テストは `tests/` に配置し、ファイル名には `test_` 接頭辞を付けます。
- FastAPI ルートのリクエスト/レスポンスの動作に焦点を当て、外部サービスや DB 接続はモック化してください。

## コミットおよびプルリクエストのガイドライン
- `main` ブランチへ直接 push してはいけません。すべての変更は作業ブランチにコミットし、必ず PR（プルリクエスト）を作成して `main` に取り込んでください。
- 最近のコミットでは、短く説明的な要約（英語）を使用しています。厳格な conventional-commit 接頭辞は使用されていません。メッセージは簡潔でアクション指向のものにしてください。
- PR（プルリクエスト）には以下を含める必要があります：明確な説明、関連するイシューへのリンク（存在する場合）、テストに関するメモ（コマンドと結果）。UI の変更に関するスクリーンショットまたは画面キャプチャは必須ではありませんが、大規模な UI 変更の場合は添付を推奨します。スクリーンショットを添付する場合は `assets/images/`（例: `assets/images/security_settings_redesign.png`）にコミットし、PR 本文から参照してください。
- PR（プルリクエスト）のタイトルと本文は、日本語と英語の両方を使って作成してください（PR titles and descriptions must include both Japanese and English）。
- エージェントは、ユーザーから明示的な指示がない限り PR をマージしてはいけません。

## エージェントの作業ルール
- 作業開始前に現在のブランチと未コミットの変更を確認してください。`main` ブランチ上では変更を行わず、作業ブランチを使用してください。
- ユーザーまたは他のエージェントによる既存の変更を、明示的な許可なく上書き、破棄、または巻き戻してはいけません。
- 変更範囲に対応するテストを実行してください。テストを実行できない場合は、その理由を最終報告に記載してください。
- 複雑または大規模な変更のうち、独立した作業へ分割して並列実行できるものは、サブエージェントを使用してください。
- サブエージェントを使用する場合は担当範囲を明確に分け、原則として同じファイルを同時に編集させないでください。
- データベーススキーマを変更する場合は、新しい Alembic migration と関連テストを追加してください。適用済みまたは既存の migration ファイルを書き換えてはいけません。
- 新しい依存関係を追加する前に、その必要性と既存の依存関係で代替できないことを確認してください。追加した場合は、理由と影響を PR に記載してください。
- ユーザーへの説明や、作業・編集途中の経過報告はすべて日本語で表示してください。

## セキュリティと設定のヒント
- 必要な環境変数には、`GROQ_API_KEY`、`GEMINI_API_KEY`、`FASTAPI_SECRET_KEY`、Resend メールの設定（`RESEND_API_KEY` および `RESEND_FROM_ADDRESS`）、PostgreSQL の設定、および Redis の設定（Redis 認証を使用する場合）が含まれます。シークレット情報は環境変数または `.env` に保持し、git には含めないでください。
- 本番環境では `FASTAPI_DEBUG` を無効にし、デプロイ前に Docker のデフォルト設定を確認してください。
- .envファイルの内容は絶対に読んではいけない
