# 開発規約

リポジトリ内でコードを変更するときに従う、構成・コマンド・実装規約・テスト方針のまとめです。行動規範（ブランチ運用、PR、並行作業、セキュリティ）は `../../AGENTS.md` にあります。

## プロジェクト構成とモジュール構成
- `app.py` はメインサーバーの FastAPI エントリーポイントです。
- `blueprints/` には機能モジュール（auth、chat、memo、prompt_share、context_vault、admin、MCP OAuth）と、それぞれのルーティング・ハンドラが含まれています。
- `services/` には、共通のインテグレーション（DB、LLM、メール、ユーザーヘルパー）が格納されています。DB アクセスは可能な限り `services/repositories/`（`chat_repository.py` など）のリポジトリ経由に寄せてください。
- `frontend/` は独立した Next.js アプリ（`strike-frontend`）です。`components/`、`hooks/`、`contexts/`、`lib/` などで構成され、スタイル方針は `frontend/STYLING_STRATEGY.md` を参照してください。バックエンドの API とやり取りする UI はここに実装します。
- `frontend/public/` には Next.js が配信する公開アセットと CSS があります。
- `alembic/versions/` には PostgreSQL のスキーマ移行履歴が保存されています。
- `tests/` には `tests/unit/` および `tests/integration/` スイート（`unittest`）と、`tests/helpers/` 配下の共通ヘルパーが含まれています。

## ビルド、テスト、開発コマンド
- Python コマンドは `python3`（および `python3 -m pip`）を使用してください。
- `docker-compose up --build` は、Docker を使用してフルスタック（FastAPI + PostgreSQL）をビルドし、実行します。
- `python3 -m pip install -r requirements.txt` は、ローカル開発用の Python 依存関係をインストールします。
- `python3 app.py` は、FastAPI アプリをローカルで起動します（必要な環境変数が設定されていることを確認してください）。
- `python3 -m unittest` はテストスイートを実行します。特定のファイルをターゲットにする場合は、`python3 -m unittest tests.unit.test_edit_default_task` のように実行します。
- フロントエンド（`frontend/`）は Node のコマンドを使用します。`npm run dev`（開発サーバー）、`npm run build`（ビルド）、`npm run lint`（ESLint）、`npm run typecheck`（型検査）、`npm run test`（ロジック + コンポーネントテスト）を実行してください。フロントエンドを変更したら、変更箇所と直接影響を受ける範囲に必要な `lint`／`typecheck`／テストを実行してください。
- 依存バージョンは完全固定（`==` および固定タグ）が必須です。`python3 scripts/check_version_locks.py` で requirements とロック、Docker イメージ、npm スペックの固定を検証できます。浮動バージョン（`^`、`~`、`latest` など）は追加しないでください。
- バックエンドの静的解析設定は `pyproject.toml` に集約されています。`python3 -m ruff check app.py blueprints services scripts tests` で lint、`python3 -m mypy` で型検査を実行します。mypy は `[tool.mypy]` の `files` に挙げたモジュールだけを検査対象とする段階導入方式で、型付けを広げるときはこのリストへ 1 行追加してください。

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
- JavaScript / TypeScript: `frontend/components/`・`frontend/hooks/`・`frontend/lib/` にある既存のモジュールパターン（機能別ディレクトリ、用途別 hook と Context への分割、`lib/` の再利用ロジック）に従い、ファイルを単一責任に保ちます。`frontend/scripts/` はブラウザ側の共通ランタイム（CSRF、テーマ、再試行付き fetch）とテストランナーの置き場で、画面ロジックは置きません。
- CSS: フロントエンド（Next.js）のスタイルは `frontend/public/static/css/` 配下にあり、`frontend/pages/_app.tsx` から import します。ベーススタイルは `frontend/public/static/css/base/` に、再利用可能なコンポーネントは `frontend/public/static/css/components/` に、ページの各エントリーポイントは `frontend/public/static/css/pages/<page>/` に配置します。ブループリント固有のスタイルは `frontend/public/<blueprint>/static/css/`（例: `frontend/public/prompt_share/static/css/`）に置きます。1 ファイルに無関係なスタイルを混在させないでください。BEM スタイルの `kebab-case` クラス名を推奨します。
- フォーマッターは強制されませんが、lint は強制されます。行長は 140 桁（`pyproject.toml` の `line-length`）で、日本語コメントは全角幅で計算されます。
- 環境変数の読み取りは `services/env_settings.py` の共通ヘルパー（`env_text`／`env_bool`／`env_int`／`env_int_in_range`／`env_float`）を使ってください。モジュールごとに独自の変換ヘルパーを再実装しないでください。

## 責務分割とファイル肥大化の防止
- 1つのファイル・関数・クラスに責務を詰め込みすぎないでください。単一責任の原則（SRP）を守り、役割が増えてきたら早めにモジュールへ分割します。
- 既存ファイルに機能を追加する際は、そのファイルの責務が肥大化しないか確認してください。関心事が異なる処理は、`services/`（共通ロジック）やブループリント配下の適切なモジュールへ切り出します。
- 関数が長くなりすぎた場合（目安として1画面に収まらない、複数の責務を持つ）は、意味のある単位に分割します。深いネストは早期リターンやヘルパー関数で平坦化してください。
- ルーティングに複雑なロジックを埋め込まず、ビジネスロジックは `services/` へ寄せ、各レイヤーの責務を明確に保ちます。
- 既存の重複や肥大化に気づいた場合でも、依頼された変更の範囲を大きく超えるリファクタリングは避け、必要に応じて PR やコメントで分割を提案してください。 ただし、触った範囲を現行の規約に揃えることはこの制限の対象外です。

## 技術的負債を増やさない
- 書き方を揃える: 触った関数・ファイルに古い書き方と現行の書き方が混在していたら、現行の規約側（`services/repositories/` 経由の DB アクセス、`services/env_settings.py` の環境変数ヘルパー、`services/api_errors.py` のエラー型、トークン経由の CSS など）に揃えてください。周囲の古い書き方を模倣して増やさないでください。
- 根本を直す: 症状を避ける分岐・フラグ・特例の追加で済ませられる場合でも、根本原因が触っている範囲にあるなら根本を直してください。範囲を超えるなら、その場しのぎを入れずに別 PR として提案します。
- 使われないコードは消す: コメントアウトやフラグでの一時停止を残さず、停止中・呼ばれていないコードに機能を足さないでください。CI の vulture は信頼度 100% の未使用しか検出しないため、呼び出し元の有無は自分で確認します。
- コメントと名前を実装に合わせる: コメントと docstring には「なぜ」を書き、実装を変えたら同じ変更で更新してください。実装と食い違うコメントや関数名を触った範囲で見つけたら直します。

## テストガイドライン
- フレームワーク: `unittest` （`tests/unit/test_edit_default_task.py` を参照）。
- 命名: テストは `tests/` に配置し、ファイル名には `test_` 接頭辞を付けます。
- FastAPI ルートのリクエスト/レスポンスの動作に焦点を当て、外部サービスや DB 接続はモック化してください。
- チャット出力の回帰データセットは `tests/fixtures/llm_eval/chat_output_cases.json` に固定し、`tests/unit/test_llm_output_eval.py` が実行します。期待値はデータ側に書くため、`tests/helpers/llm_eval.py` が読み込み時に形式・参照・ID 重複を検証し、壊れたデータはテスト失敗にします。
- このデータセットで判定するのは、実行ごとに揺れない観点（引用先が入力に存在する、不正な根拠IDが本文に残らない、生成 UI の状態と品質ゲートの判定）だけです。文章の良し悪しは判定しません。ケースを足すときは根拠IDを手書きせず、出典は `label` で参照し `{{cite:label}}` を本文に書きます。
- ケースを足したら、そのケースが守っている規則を実装側で一時的に壊し、テストが落ちることを確認してから固定します。落ちないケースは回帰を検出できていないため、期待値の粒度（どの指摘が出るか、本文がどう残るか）を上げます。

## UI 実装規約
- トークンの正本は `frontend/public/static/css/base/variables.css`、役割別の一覧と選び方は `frontend/DESIGN_TOKENS.md`、CSS の配置方針は `frontend/STYLING_STRATEGY.md` です。ここには配色や操作の原則だけを置き、色の数値は書きません。新しい UI は既存トークンから選び、既存画面と浮かないことを優先してください。
- ホバー（`:hover`）だけで現れる操作はタッチ端末では触れません。タップで開く導線を必ず用意し、ポインタを持たない端末で同じ操作ができるかを実装前に確認してください。
- アイコンだけのボタンは、タップ領域を 44×44px 以上にしてください。
- 色は `variables.css` のトークンで定義し、コンポーネントやページの CSS に生の 16 進数を書かないでください。
- 面を明度差だけで分けないでください。面の区別は線（`--border-default`）と余白で作り、強調は濃色面に白文字を載せる反転で作ります。
- 補助テキストを薄くするために不透明度を下げないでください。副次テキスト用のトークン（`--text-secondary`）を使います。
- 失敗を表す色（`--danger-color`）はエラー表示だけに使い、削除ボタンなど「危険だが失敗ではない」操作には使わないでください。
- 反転面（濃色の面）のフォーカスリングを、その面と同じ色にしないでください。白地では地色のオフセットを挟み、濃色面では白のリングを使います。
- 濃色面では白地用の線色や副次色はコントラストが取れません。濃色面専用のトークンを使い、白地用の値を流用しないでください。

## サブエージェントの指定
`AGENTS.md` が要求する 2 種類のサブエージェントの指定です。ツールやモデルの名称が変わったら、この表だけを更新します。

| 役割 | 用途 | Codex | Claude Code |
| --- | --- | --- | --- |
| レビュー用サブエージェント | PR を作る前の独立レビュー（スコープ・差分・チェックリストだけを渡す） | luna max | Sonnet 5 |
| LLM 代替サブエージェント | 「AI 出力の品質確認」で LLM API の代わりに応答を生成する | luna | Sonnet 5 |

## AI 出力の品質確認
- 対象は LLM に渡す内容や応答の扱いを変える変更です。例: プロンプト文言（`blueprints/chat/tasks.py`、`services/chat_prompt.py`、`services/prompt_assist.py`）、ツール定義（`services/llm_tool_schema.py`）、会話・コンテキストの組み立てと判断ループ（`services/chat_generation.py`）、モデル名・温度・出力上限などの設定。
- 実 API は呼ばず、LLM 代替サブエージェント（「サブエージェントの指定」参照）を LLM API の代わりに使います。変更前と変更後のプロンプト・ツール定義・会話を実装と同じ手順で組み立て、同じ入力に対する出力を得てください。
- 入力は代表的なケースを 3〜5 件用意します。通常ケースに加え、変更で改善を狙ったケースと、退行しやすいケース（長い文脈、ツール呼び出しが要る質問、日本語と英語の混在など）を含めます。
- 判定は観点を先に決めて行います。例: 指示への追従、事実性と出典、形式（JSON やツール呼び出しの契約）、冗長さ、口調。変更前後の出力を並べ、観点ごとにどちらが良いかを根拠付きで記録します。
- 品質が上がったと確認できない場合は PR にせず、原因を調べて修正するかユーザーに報告してください。比較に使った入力・観点・結果は PR 本文に書きます。
- この比較は本番のプロバイダ・モデル（Groq、OpenAI、Anthropic 上の各モデル）とは別のモデルで行うため、確認できるのは指示文・文脈の組み立て・ツール説明文の改善方向までです。ツール引数のサーバー側検証（[ADR 0008](../decisions/0008-provider-safe-tool-schemas.md)）、出力上限の扱い、ストリームイベントの形式などプロバイダ固有の挙動は確認できません。JSON やツール呼び出しの契約が変わる場合は、`services/llm_tool_schema.py` や `services/chat_generation.py` の既存の単体テストで担保し、足りなければ同じ変更でテストを追加してください。
