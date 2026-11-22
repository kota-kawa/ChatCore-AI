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
| LLM の出力 ↔ 宣言的UIの描画 | 非信頼のJSON・式・アクション | 部品・プロパティ・参照と計算量を検証し、任意コード・HTML・画像URLを禁止。画像は選定済み署名付き中継だけ。会話操作は入力欄への反映だけで、書き込み承認を代替しない | `services/structured_ui_models.py`、`services/structured_ui.py` | [内部設計](../../ARCHITECTURE.md#ネイティブ生成uiとartifact) |
| LLM の出力 ↔ 生成 UI の実行 | LLM が生成した HTML・CSS・JavaScript | スキーマ検証を唯一の通過点にし、隔離 iframe で実行、親アプリの CSP `frame-src 'self'` で遷移を塞ぐ。画像は `data:`／`blob:` と、サーバーが選定した検索画像の署名付き中継パスだけを許す | `services/generative_ui*.py`、`services/web_search_image_proxy.py`、`frontend/next.config.mjs` | [deep dive 9.6](system_design_deep_dive.md#96-生成uiサンドボックスアーティファクト)、[22.6](system_design_deep_dive.md#226-aiが生成した表示はサーバー検証とサンドボックスの二重で守る) |
| LLM の提案 ↔ 画面操作 | LLM が提案した操作計画 | カタログとホワイトリスト照合、危険操作は確認モーダル、機微な入力値は LLM へ渡さない | 画面操作エージェント（`blueprints/chat/` と `frontend/`） | [deep dive 14.6〜14.7](system_design_deep_dive.md#146-危険な操作への追加確認) |
| 外部 AI クライアント ↔ MCP | 接続元の身元と要求権限 | OAuth 同意とスコープ、短命で一度だけの認可コード、トークンの暗号化保存、登録・認可・操作ごとのレート制限 | `services/mcp_oauth.py`、`services/mcp_request_protection.py` | [deep dive 15.2](system_design_deep_dive.md#152-認証と同意)、[15.4](system_design_deep_dive.md#154-mcpの安全性) |
| 外部データ ↔ プロンプト | 検索結果、URL 取得本文、公開コンテンツ、MCP 経由で返す本文 | 命令ではなく利用者提供のデータとして扱い、システム指示の上書きを認めない | `services/chat_url_context.py`、`services/chat_prompt.py` | [deep dive 8.6](system_design_deep_dive.md#86-aiへ送るデータの扱い)、[18.4](system_design_deep_dive.md#184-web検索とurl取得)、[ADR 0010](../decisions/0010-on-demand-web-page-reading.md) |
| LLM のツール呼び出し ↔ 利用者データの書き込み | モデルが提案した書き込み（メモの変更、公開 Prompt の新規投稿、Task・個人 Skill の変更） | 生成中に実行せず、所有者と提案時の版を再確認してから承認後に実行。公開 Prompt は新規投稿のみで既存投稿の編集はできず、Web 投稿と同じ作成制限を適用し、非公開テキストとの一致警告には利用者の確認を求める。「常に承認」は外部の内容、または検索で本人由来でない未確認の記憶を読んだターンでは自動実行しない | `services/chat_tool_approval_service.py`、`services/chat_workspace_tools/`、`blueprints/chat/tool_approvals.py` | [deep dive 9.8](system_design_deep_dive.md#98-チャットの書き込みツールと承認カード)、[ADR 0013](../decisions/0013-chat-writes-through-stored-approvals.md) |

## AI 安全方針とアプリ側の強制範囲

基本システムプロンプトは有害な支援を避けること、医療・法律・金融などの判断を根拠に合わせて慎重に扱うこと、信頼できない文章を命令として扱わないことをモデルへ指示します。自由文の回答がその指示を守ったかを判定するアプリ側の汎用分類器はありません。下表は、指示だけで担保する項目とサーバーが機械的に拒否・保留する操作を分けます。

| プロンプト上の方針 | アプリ側の強制 | 実装・境界 |
| --- | --- | --- |
| 深刻な危害への具体的支援を避け、高リスク分野では根拠に見合う慎重さを保つ | 回答文の安全性を判定する汎用ゲートはない。ツールのスコープ・引数・所有者・承認状態は別途サーバーで検査する | 方針は `services/chat_prompt.py`。ツール検証は各 `services/chat_workspace_tools/` と `services/mcp_tools/` |
| 指示の優先順位を守り、引用・記憶・ツール結果を命令として扱わない | 外部入力を読んだターンでは「常に承認」の自動実行を抑止する。記憶の検索ツール `memory_search` の結果に、本人由来でない未確認の記憶（MCP・取り込みで入り、本人が確認していないもの）が 1 件でも含まれたターンも同じ抑止へ入れる。本人由来は、本人が確認した記憶と、チャットから抽出した記憶（`source_kind` が `chat`）で、その定義は `services/memory_trust.py` の 1 か所にあり、`<user_memory>` を本人由来で絞る SQL 条件と、結果の判定が同じ定数から作る。毎ターン文脈へ入れるまとめ `<user_memory>` は本人由来だけで組むため、読んだだけでは抑止しない。メモ専用の `personal_knowledge_search` は本人のデータなので、記憶に由来する抑止は起きない（[ADR 0025](../decisions/0025-always-on-memory-with-provenance.md)）。内容の真偽や自由文の従い方までは判定しない | `services/chat_generation_tools.py`、`services/chat_tool_calls.py`、`services/chat_workspace_tools/runner.py`、`services/memory_search.py`、`services/memory_trust.py`、`services/personal_knowledge.py`、`services/user_memory.py` |
| 操作が完了したと主張するのはツール結果が確認できた場合だけ | 承認・実行結果と食い違う書き込み完了の申告を回答側で検査する。警告・承認待ちのカードも結果状態に合わせる | `services/chat_write_claim_guard.py`、`services/chat_tool_approval_service.py`、`tests/unit/test_chat_generation_failure_recovery.py` |
| 書き込みや外部操作には明示された権限と確認条件を使う | スコープ、利用者 ID、型付き引数、版番号、レート制限、承認カードをサーバー側で検証する | `services/mcp_oauth.py`、`services/mcp_tools/`、`services/chat_workspace_tools/`、`services/chat_tool_approval_service.py` |
| 記憶された事実は古い可能性があり、最新の本人発話と矛盾するときは最新の発話を優先する | 事実の出所・確信度・本人の最終確認を保存して検索結果に含める。未確認事実は回答から除外せず、本人由来でないものを含む検索のターンだけ無条件の自動書き込みを抑止する | `context_facts.confidence`、`context_facts.last_confirmed_at`、`services/memory_search.py`、`services/memory_trust.py`、[ADR 0016](../decisions/0016-context-fact-confirmation.md)、[ADR 0023](../decisions/0023-auto-save-extracted-memory.md) |

機微な個人情報（健康、信条、政治的な意見、性的指向、犯罪歴、詳細な金銭の状況）は、本人が同じ発話の中で覚えるよう頼んだときだけ記憶します。抽出の LLM が候補ごとにカテゴリと、頼んだ一節を出力し、`services/context_vault_extraction.py` が、カテゴリに当たる候補の一節が本人の発話に含まれること（アシスタントの応答の中の「覚えておきます」は数えない。`evidence` と同じ正規化の照合）を確かめ、含まれなければ候補を落とします。カテゴリと一節は保存しません。LLM がカテゴリを申告しない機微な内容はこの検証では止められないため、プロンプトの規則と、記憶の画面での確認と無効化で抑えます。この規則の前に保存された記憶は対象外です（[ADR 0025](../decisions/0025-always-on-memory-with-provenance.md)）。

チャットから記憶を保存するとき、根拠にした本人発話の一節（発話と照合した引用）を `context_fact_sources` に保存します。引用は秘密情報の検査（title・content と同じ正規表現）を通ったものだけで、1 件 1000 文字までです。API には返さず、事実・ルームの削除とアカウント削除（FK の CASCADE）で一緒に消えます。事実の文面が変わる更新では、引用が裏づけなくなるため削除します。

保存前の照合（既存の記憶との追加・更新・言い換えの判定）は、記憶の文面と本人の発話から抽出した候補を JSON で包んだ入力として LLM に渡し、入力の中の指示を実行しないよう system 指示で縛ります。判定は文面を作り直さず、応答は pydantic で厳格に検証して対象の id を候補ごとに渡した一覧に限り、検証に通らないものは判定が無いものとして照合の導入前の挙動（BM25 で有効な記憶と重複とみなされた候補は再言及、それ以外は新しい記憶）へ倒します。語の重なりで重複とみなされる食い違いも、再言及として吸収せずに照合へ回します。本人が無効化した記憶・却下した候補と同じ内容は、有効な記憶に最良一致していても、新しい記憶として保存しません（保存の段で、これらだけを対象にした BM25 をもう一度かけて確かめます）。記憶を無効化できる更新は、対象が本人の有効な記憶で、判定の時点の `revision` のままのときだけ適用し、本人が無効化した記憶は置き換えません。判定に使った記憶の文面と応答はログに出しません（保存の失敗にも例外の文面を出さず、種類だけを残します）。

毎ターン文脈へ入れる記憶のまとめ（`<user_memory>`）の文面は利用者データであり指示ではありません。説明文でそう明示し、`services/user_memory.py` が記憶の文面を、正規化が変わらなくなるまで繰り返してから 1 行にまとめ、残った `&` `<` `>` をすべて全角（＆ ＜ ＞）にします（"R&D" は "R＆D" になります）。文脈の組み立てがブロック全体を再正規化（`html.unescape` を含む）しても記憶由来の ASCII の `<` `>` `&` は残らず、二重エンコードした実体参照も含めて閉じタグなどでブロックの構造を壊せません。まとめは設定（`users.memory_use_enabled`）で切れ、一時チャットとゲストでは読まず、ユーザー行が読めないときも使いません。読み込みに失敗した場合のログには例外の種類だけを残し、記憶の文面は出しません。

MCP の書き込みスコープへの同意は、そのクライアントに保存操作を許可するもので、個々の事実を本人が読んで確認したことにはなりません。MCP/import 由来で `last_confirmed_at` が NULL の事実は、チャットの記憶の検索結果に未確認として出し、そのターンの「常に承認」を抑止します（チャットから抽出した事実は本人由来として抑止しません）。利用者が Web UI から事実の内容を編集すると確認時刻を記録します。

## プロンプトインジェクションへの方針

LLM の出力も、外部から取得した本文も、「LLM が作った」「外部が返した」という理由では信頼しません。最終的な権限は、サーバー側のスキーマ検証とホワイトリスト、そして利用者の確認に置きます。秘密情報や指示の混入を完全に検出することは保証しないため、利用者は共有や外部 AI 連携の前に送信内容を確認する前提です。

## ツールと操作のリスク分類

- 画面操作エージェントは「読む・下書きする・移動する」だけの操作を確認不要とし、送信・保存・削除など取り消しにくい操作はすべて確認必須です（deep dive 14.6）。
- MCP の権限はスコープ単位で、同意画面で確認した範囲だけを許可します（deep dive 15.2）。
- 生成 UI の JavaScript は、外部通信や遷移を試みる記述を検査で落とします（deep dive 9.6）。
- チャットの書き込みツールは、読み取り（一覧・検索・全文読み取り）だけ確認不要でその場に実行し、書き込み（作成・追記・書き換え）は取り消しにくい操作として必ず承認カードを経由します。「常に承認」で確認を省いた場合も、そのターンが外部の内容、または本人由来でない未確認の記憶事実を読んでいれば自動実行を止めます（deep dive 9.8、ADR 0013、ADR 0016）。
- 新しいツールや操作を追加するときは、上のいずれかの分類に当てはめ、当てはまらない場合は確認必須側に置いてください。

## シークレット

- `.env` は読まず、コミットしません。実行時に読む環境変数の一覧は `.env.example` が正本で、`python3 scripts/check_env_documentation.py` が同期を検証します。
- MCP OAuth トークンの暗号化鍵 `MCP_OAUTH_ENCRYPTION_KEYS` は Fernet 鍵のカンマ区切りで、先頭が現在の鍵です。新しい鍵を先頭に追加し、旧鍵を残したまま配布することでローテーションできます（`services/mcp_config.py`）。

## 検証

- 単体テスト: `tests/unit/test_csrf_protection.py`、`test_security.py`、`test_auth_session.py`、`test_account_sessions.py`（待機セッションの切り替え・ログアウト・Cookie の改ざん）、`test_mcp_session_bypass.py`、`test_mcp_oauth.py`、`test_mcp_oauth_routes.py`、`test_generated_ui_reliability.py`、`test_chat_tool_approval_api.py`（所有者確認・CSRF・レート制限・承認カードの状態遷移）、`test_chat_workspace_tools.py` と `test_personal_knowledge.py`（外部・未確認の内容を読んだターンでの自動承認の抑止）。
- CI: `.github/workflows/tests.yml` の `dependency_audit` ジョブが依存パッケージの既知の脆弱性を検査し、`deploy` ジョブは全検査の成功を前提にします。
- 変更時: 状態を変更するルートを追加したら CSRF 適用を確認し、LLM へ渡すデータや LLM の出力を実行する経路を追加したら、上の信頼境界の表に行を足してください。
