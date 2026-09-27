# Security model

信頼境界と、脅威ごとの対策がどこに実装・記述されているかの索引です。詳細は各リンク先が正本で、この文書には本文を複製しません。境界や対策を変えたら、該当行を同じ変更で更新してください。

## 守る対象

- セッションと認証情報。本体は Redis、ブラウザには署名付きの参照値だけを置きます。
- 利用者のチャット履歴、メモ、パーソナル・コンテキスト、添付ファイル。
- MCP OAuth の認可コード・トークンと、その暗号化鍵。
- LLM プロバイダやメール送信の API キー。

## 信頼境界

| 境界 | 信頼しないもの | 対策 | 実装 | 記述 |
| --- | --- | --- | --- | --- |
| ブラウザ ↔ バックエンド | Cookie の内容、状態変更リクエストの出自 | Cookie は参照値のみ、状態変更に CSRF トークン、共通ミドルウェアでセキュリティヘッダー付与 | `services/session_middleware.py`、`services/csrf.py`、`services/security_headers.py` | [deep dive 8.2〜8.3](system_design_deep_dive.md#82-セッションの保存) |
| 利用者入力 ↔ 業務ロジック | 型検査に通っただけの入力 | ログイン・所有者・共有トークン・版番号・クォータを各処理で確認 | 各 blueprint と `services/repositories/` | [deep dive 8.4](system_design_deep_dive.md#84-入力と所有者の確認) |
| LLM の出力 ↔ 生成 UI の実行 | LLM が生成した HTML・CSS・JavaScript | スキーマ検証を唯一の通過点にし、隔離 iframe で実行、親アプリの CSP `frame-src 'self'` で遷移を塞ぐ | `services/generative_ui*.py`、`frontend/next.config.mjs` | [deep dive 9.6](system_design_deep_dive.md#96-生成uiサンドボックスアーティファクト)、[22.6](system_design_deep_dive.md#226-aiが生成した表示はサーバー検証とサンドボックスの二重で守る) |
| LLM の提案 ↔ 画面操作 | LLM が提案した操作計画 | カタログとホワイトリスト照合、危険操作は確認モーダル、機微な入力値は LLM へ渡さない | 画面操作エージェント（`blueprints/chat/` と `frontend/`） | [deep dive 14.6〜14.7](system_design_deep_dive.md#146-危険な操作への追加確認) |
| 外部 AI クライアント ↔ MCP | 接続元の身元と要求権限 | OAuth 同意とスコープ、短命で一度だけの認可コード、トークンの暗号化保存、登録・認可・操作ごとのレート制限 | `services/mcp_oauth.py`、`services/mcp_request_protection.py` | [deep dive 15.2](system_design_deep_dive.md#152-認証と同意)、[15.4](system_design_deep_dive.md#154-mcpの安全性) |
| 外部データ ↔ プロンプト | 検索結果、URL 取得本文、公開コンテンツ、MCP 経由で返す本文 | 命令ではなく利用者提供のデータとして扱い、システム指示の上書きを認めない | `services/chat_url_context.py`、`services/chat_prompt.py` | [deep dive 8.6](system_design_deep_dive.md#86-aiへ送るデータの扱い)、[18.4](system_design_deep_dive.md#184-web検索とurl取得)、[ADR 0010](../decisions/0010-on-demand-web-page-reading.md) |
| LLM のツール呼び出し ↔ 利用者データの書き込み | モデルが提案した書き込み（メモの作成・追記・書き換え） | 生成中に実行せず、承認待ちの行をサーバーへ保存して利用者の確認後にのみ実行。「常に承認」は外部の内容を読んだターンでは自動実行しない | `services/chat_tool_approval_service.py`、`services/chat_workspace_tools/`、`blueprints/chat/tool_approvals.py` | [deep dive 9.8](system_design_deep_dive.md#98-チャットの書き込みツールと承認カード)、[ADR 0013](../decisions/0013-chat-writes-through-stored-approvals.md) |

## プロンプトインジェクションへの方針

LLM の出力も、外部から取得した本文も、「LLM が作った」「外部が返した」という理由では信頼しません。最終的な権限は、サーバー側のスキーマ検証とホワイトリスト、そして利用者の確認に置きます。秘密情報や指示の混入を完全に検出することは保証しないため、利用者は共有や外部 AI 連携の前に送信内容を確認する前提です。

## ツールと操作のリスク分類

- 画面操作エージェントは「読む・下書きする・移動する」だけの操作を確認不要とし、送信・保存・削除など取り消しにくい操作はすべて確認必須です（deep dive 14.6）。
- MCP の権限はスコープ単位で、同意画面で確認した範囲だけを許可します（deep dive 15.2）。
- 生成 UI の JavaScript は、外部通信や遷移を試みる記述を検査で落とします（deep dive 9.6）。
- チャットの書き込みツールは、読み取り（一覧・検索・全文読み取り）だけ確認不要でその場に実行し、書き込み（作成・追記・書き換え）は取り消しにくい操作として必ず承認カードを経由します。「常に承認」で確認を省いた場合も、そのターンが外部の内容を読んでいれば自動実行を止めます（deep dive 9.8、ADR 0013）。
- 新しいツールや操作を追加するときは、上のいずれかの分類に当てはめ、当てはまらない場合は確認必須側に置いてください。

## シークレット

- `.env` は読まず、コミットしません。実行時に読む環境変数の一覧は `.env.example` が正本で、`python3 scripts/check_env_documentation.py` が同期を検証します。
- MCP OAuth トークンの暗号化鍵 `MCP_OAUTH_ENCRYPTION_KEYS` は Fernet 鍵のカンマ区切りで、先頭が現在の鍵です。新しい鍵を先頭に追加し、旧鍵を残したまま配布することでローテーションできます（`services/mcp_config.py`）。

## 検証

- 単体テスト: `tests/unit/test_csrf_protection.py`、`test_security.py`、`test_auth_session.py`、`test_mcp_session_bypass.py`、`test_mcp_oauth.py`、`test_mcp_oauth_routes.py`、`test_generated_ui_reliability.py`、`test_chat_tool_approval_api.py`（所有者確認・CSRF・レート制限・承認カードの状態遷移）、`test_chat_workspace_tools.py`（外部の内容を読んだターンでの自動承認の抑止）。
- CI: `.github/workflows/tests.yml` の `dependency_audit` ジョブが依存パッケージの既知の脆弱性を検査し、`deploy` ジョブは全検査の成功を前提にします。
- 変更時: 状態を変更するルートを追加したら CSRF 適用を確認し、LLM へ渡すデータや LLM の出力を実行する経路を追加したら、上の信頼境界の表に行を足してください。
