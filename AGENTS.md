# リポジトリガイドライン

## プロジェクト構成とモジュール構成
- `app.py` はメインサーバーの FastAPI エントリーポイントです。
- `blueprints/` には機能モジュール（auth、chat、memo、prompt_share、admin）と、それぞれのルーティング、テンプレート、静的アセットが含まれています。
- `services/` には、共通のインテグレーション（DB、LLM、メール、ユーザーヘルパー）が格納されています。
- `templates/` および `static/` はグローバルな HTML/CSS/JS アセットです。ブループリント固有のアセットは、各ブループリントの `templates/` および `static/` フォルダ配下にあります。
- `alembic/versions/` には PostgreSQL のスキーマ移行履歴が保存されています。
- `tests/` には `unit/` および `integration/` スイート（`unittest`）と、`tests/helpers/` 配下の共通ヘルパーが含まれています。

## ビルド、テスト、開発コマンド
- `docker-compose up --build` は、Docker を使用してフルスタック（FastAPI + PostgreSQL）をビルドし、実行します。
- `pip install -r requirements.txt` は、ローカル開発用の Python 依存関係をインストールします。
- `python app.py` は、FastAPI アプリをローカルで起動します（必要な環境変数が設定されていることを確認してください）。
- `python -m unittest` はテストスイートを実行します。特定のファイルをターゲットにする場合は、`python -m unittest tests.unit.test_edit_default_task` のように実行します。

## コーディングスタイルと命名規則
- Python: 4スペースのインデント、関数や変数には `snake_case`、クラスには `CapWords` を使用します。
- JavaScript: `static/js/` にある既存のモジュールパターンに従い、ファイルを単一責任に保ちます。
- CSS: `static/css/` にあるリポジトリのガイダンスに従います。ベーススタイルは `static/css/base/` に、再利用可能なコンポーネントは `static/css/components/` に、ページの各エントリーポイントは `static/css/pages/<page>/index.css` に配置します。BEM スタイルの `kebab-case` クラス名を推奨します。
- フォーマッターは強制されません。変更は周囲のコードと整合性を保つようにしてください。

## テストガイドライン
- フレームワーク: `unittest` （`tests/unit/test_edit_default_task.py` を参照）。
- 命名: テストは `tests/` に配置し、ファイル名には `test_` 接頭辞を付けます。
- FastAPI ルートのリクエスト/レスポンスの動作に焦点を当て、外部サービスや DB 接続はモック化してください。

## コミットおよびプルリクエストのガイドライン
- 最近のコミットでは、短く説明的な要約（英語）を使用しています。厳格な conventional-commit 接頭辞は使用されていません。メッセージは簡潔でアクション指向のものにしてください。
- PR（プルリクエスト）には以下を含める必要があります：明確な説明、関連するイシューへのリンク（存在する場合）、テストに関するメモ（コマンドと結果）、および UI の変更に関するスクリーンショットまたは画面キャプチャ。

## セキュリティと設定のヒント
- 必要な環境変数には、`GROQ_API_KEY`、`GEMINI_API_KEY`（従来の `Gemini_API_KEY` も使用可能）、`FASTAPI_SECRET_KEY`、Resend メールの設定（`RESEND_API_KEY` および `RESEND_FROM_ADDRESS`）、PostgreSQL の設定、および Redis の設定（Redis 認証を使用する場合）が含まれます（`FLASK_SECRET_KEY` はレガシーなフォールバックとして保持されています）。シークレット情報は環境変数または `.env` に保持し、git には含めないでください。
- 本番環境では `FASTAPI_DEBUG` を無効にし、デプロイ前に Docker のデフォルト設定を確認してください。
