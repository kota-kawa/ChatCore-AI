# デバッグと既知の失敗パターン

この文書は、再現条件が分かりにくい障害を実装の境界から切り分けるための手順です。環境変数の値や秘密情報をログ・文書へ転記しません。

## 最初に確認する共通情報

1. `git status --short` で未コミット変更を確認し、既存の作業を原因と決めつけない。
2. ブラウザの Network と API のレスポンスステータスを確認する。リクエスト ID がある場合は `X-Request-ID` を使ってサーバーログを絞る。
3. `GET /healthz` と `GET /readyz` を別々に確認する。前者が成功して後者が失敗する場合、プロセスではなく DB などの依存先を調べる。
4. 変更が API 契約、DB、フロントのどの境界をまたぐかを `ARCHITECTURE.md` で確認し、対象テストを先に特定する。

## PostgreSQL 接続・起動待ち

### 症状

- コンテナは起動しているが `/readyz` が DB エラーを返す。
- 起動直後だけ DB 接続エラーになる。
- 並列リクエスト時だけ接続プール枯渇が発生する。

### 確認する境界

- `services/health.py` が readiness で確認している DB 操作。
- `services/db.py` の `AsyncEngine`、`AsyncAdaptedQueuePool`、`pool_pre_ping`、接続取得タイムアウト、`AsyncSession`のrollback。
- Docker Compose の DB の healthcheck と、アプリの `depends_on`／entrypoint の migration 実行順。

### 切り分け

- 起動直後だけなら、アプリを変更する前に DB の healthcheck と migration の完了順を確認する。
- 接続先の問題なら、実際のコンテナ構成と `POSTGRES_HOST`／`DATABASE_URL` の関係を確認する。
- プール枯渇なら、`AsyncSession`がスコープ終了時に閉じられているか、未完了transactionが残っていないかを確認する。上限値だけを増やすとリークを隠す可能性がある。
- DB スキーマ不足なら、既存 revision を編集せず `alembic/versions/` に新しい migration を追加する。

対象コードの単体テストでは DB 接続をモックし、統合テストではルートの結果とエラー変換を確認します。秘密情報を含む設定ファイルを読んで診断結果へ貼り付けないでください。

## Redis・セッション・キャッシュ

### 重要な境界

`services/cache.py` は Redis の接続失敗後に短いクールダウンを設け、キャッシュやシングルフライトを利用できない状態を返します。一方、`services/session_middleware.py` のセッション本体は Redis に保存されます。Cookie に入るのは署名済みの Redis 参照 ID だけで、Redis 障害時にセッション辞書を Cookie に保存する設計ではありません。

### 症状別の確認

- ログイン直後にセッションが維持されない場合は、Redis の ping、`session:<id>` の保存、レスポンスの `Set-Cookie` を確認する。Redis 障害時は安全のため Cookie が消去され、再認証が必要になる。
- 起動シードや定期クリーンアップが複数ワーカーで重複する場合は、`try_acquire_single_flight` と TTL を確認する。Redis が使えない単一プロセス相当では処理が継続するため、処理自体を冪等に保つ。
- チャットの停止・再接続だけが不安定な場合は、セッションと生成イベントを分けて調べる。生成イベントのリプレイ／Pub/Sub は `services/chat_generation.py`、セッションは `services/session_middleware.py` が担当する。

Redis 障害をテストする場合は、実 Redis を前提にせず、`get_redis_client()` の失敗、`set`／`get` の例外、Pub/Sub の通知欠落をモックで決定的に再現します。機密セッションを署名 Cookie にフォールバックさせる修正はセキュリティ境界を変えるため、独立した ADR とセキュリティテストが必要です。

## チャット SSE の切断・再接続

### 確認順序

1. ブラウザで `/api/chat` の開始リクエストと `/api/chat_generation_stream` のストリームを分けて確認する。
2. SSE の event 名、連番、`done`／`aborted`／`error`／`incomplete` を確認する。本文が途中で止まっただけか、ジョブ自体が終了したかを区別する。`: keepalive` はイベントIDを持たない接続維持コメントであり、生成進捗やアイドルタイムアウトのリセットには数えない。
3. `services/chat_generation_job_base.py` のジョブ状態、キャンセル要求、イベント履歴、永続化の一度きり制御を確認する。
4. `blueprints/chat/messages.py` の再接続・ステータス・停止ルートと、`frontend/hooks/chat_page/use_home_page_generation_actions.ts` の Abort／再接続処理を照合する。
5. 外部 LLM の実通信の前に、生成ストリームをモックして「接続切断」「再接続」「途中停止」「プロバイダエラー」をテストする。

完了通知と停止通知の競合で二重保存しやすいため、永続化処理をルートへ追加せず `ChatGenerationJob` の一度きり制御を通します。フロントの表示だけを直す場合も、サーバーが返すイベント契約を先に確認します。

終端イベントの後も停止ボタンや生成中の吹き出しが残って見える場合は、先に `frontend/tests/generation_stream_consumer.test.ts` のハーネスで、同じ量の `chunk` と終端イベントを流して再現を試みます。約10万文字の本文と `incomplete` を流しても、ストリーム消費層は数十ミリ秒で `streaming:false` になり終端します。消費層が正しく終わるなら、原因は生成そのもの（本文の肥大化や生成時間）にあるので、「チャット回答に内部形式が混ざる・短い依頼が膨らむ」の手順で確認します。

## チャット回答に内部形式が混ざる・短い依頼が膨らむ

### 症状

- 回答に `assistant to=functions.web_search`、`multi_tool_use.parallel`、`<|im_end|>`、`</|assistant|>`、`</parameter>` などのツール呼び出し形式や特殊トークンが混ざる。
- `Need only phrase.` や `/final` のようなモデル内部の推論らしき英語、化け文字、同じ回答の二重化が本文に出る。
- 「〜とだけ返して」のような短い依頼が出力上限まで膨らみ、`first_pass_finish_reason=max_output_tokens` や `continuation_stalled=true` で終わる。

### 確認する境界

- `services/llm.py` のプロバイダ別の呼び出し経路。GPT-6 Luna は Chat Completions ではツールと推論を併用できず（推論を付けると 400 で「function tools を使うなら /v1/responses」と返る）、推論 `none` で呼ぶと上記の崩れが起きる。Luna へツールを渡すターンは Responses API に載せ、Chat Completions 形のツール履歴を `function_call`／`function_call_output` に写す。Responses API の function tool は既定で strict なので、[ADR 0008](../decisions/0008-provider-safe-tool-schemas.md) の緩めたスキーマを保つには `strict: false` を明示する。
- `services/llm_protocol_leak.py` の漏れガードは、`services/chat_generation_llm_stream.py` の `_iter_llm_stream_with_retry` で本文にツール形式が出た位置で打ち切り、ストリームを閉じる。発動するとテレメトリの `protocol_leak_truncations` が増える。新しいモデルの形式（例: Qwen の XML 風タグ）が漏れたら、観測した形をテストに足してからパターンに加える。コードブロックとインラインコードの中は、利用者が形式そのものを尋ねた回答でありうるので対象外にしている。

### 検証方法

- 崩れは確率的で、1回の実行では正常に見えることが多い。判断ループが最初に送る要求（メッセージとツール定義）を捕捉して保存し、同じ要求で変更前後の生出力を**直列に**各8回ほど取って崩れの件数を比べる。並列に投げるとレート制限や上流エラーが混ざり、計測が無効になる。
- 生出力は `strip_turn_state_update` で内部封筒を除いてから判定する。期待される短答（「テスト完了」など）との完全一致と、上記の形式を探す正規表現で機械的に数えられる。

長い調査後の回答が短い、または途中で終わる場合は、ログの `terminal_event`、`agent_steps`、`llm_turns`、`tool_calls`、`web_search_count`、`continuation_count`、`continuation_stalled`、`output_chars`、`duration_seconds` を同じリクエストで確認します。`incomplete` は部分回答を保存済み、`done` はプロバイダが正常終了したことを表します。OpenAI Responses の `response.incomplete`、Chat Completions の `finish_reason=length`、Claude の `stop_reason=max_tokens` は LLM 層で出力上限として検出されます。`LLM_FINAL_ANSWER_MAX_CONTINUATIONS=0` で継続生成を無効化でき、既定値は3です。`continuation_stalled=true` は継続が重複部分だけで終わった状態なので、本文は保存済みですが完了扱いではありません。本文に `assistant to=functions.…` や `<|im_end|>` のような内部のツール呼び出し形式が混ざり始めた場合は、その位置で本文を切ってストリームを閉じ、`protocol_leak_truncations` が増えます（コードの中は対象外）。これが多いモデルは、ツール付きの要求で推論が崩れていないか `services/llm.py` の呼び出し経路を確認します。最後の判断が本文を返さなかった場合（内部封筒だけ、無出力、出力上限で本文ゼロ）は `empty_answer_recoveries` が 1 になり、内部封筒を要求しない回答のみの契約で同じ判断を1度だけやり直します。メモツールが有効でカードがまだ無い場合は、再試行でツールと直近の読み取り結果を残し、未提出の操作を続けられるようにします。回復後も本文が無ければ `error`（`AIからの回答が空でした`）で終わり、検索画像だけ・「回答までのステップ」だけの応答は保存しません。タグ（`<turn_state_update>`）を付けずに封筒の JSON だけを返した判断も本文ゼロとして扱い、その JSON で状態を更新したうえで同じやり直しに乗せます。このとき `untagged_turn_state_recoveries` が増え、回答として保存されません。停止・失敗時にバッファから救出する本文にも同じ判定を使います。利用者が内部キー名（`ready_to_answer` など）を挙げた発話では、JSON の回答を求められている可能性があるため判定しません。`missing_turn_state_updates` はツールを呼んだ判断ステップでタグ付きの封筒を読めなかった回数です。封筒は次の判断へ状態を渡すためのものなので、契約はツールを呼ぶ判断にだけ封筒を求め、そのまま回答する判断と、封筒を省かせる回復ステップは数えません。`done` で終わったターンでもこれが多いモデルは封筒の契約に従えていません。ただし GPT-OSS 120B（Groq）はツールを呼ぶ応答で本文を1文字も返さないため、ツールを呼ぶ判断では構造的に毎回数えられます（2026-09 の実測で 44/44）。この指標の増減はモデルごとに比べてください。

会話の途中や最後で `error` だけが表示される場合は、ログの `salvaged_partial_answers`、`research_failure_recoveries`、`llm_turn_budget_exhausted`、`llm_error_type` を確認します。判断ステップの本文は「ツール呼び出しが無い」と確定するまで配信されないため、その前に落ちると本文はバッファにしか存在しません。`salvaged_partial_answers=1` はそのバッファを救出して`incomplete` で保存した状態で、`error` で終わるのは本文が1文字も無いターンだけです。`research_failure_recoveries=1` は調査ステップがプロバイダ障害で落ち、ツールを外した回答へ縮退したことを表します。`llm_error_type` が `LlmProviderError`（再試行不可の汎用）の場合は、`services/llm.py` の `_map_provider_exception` がその例外を分類できていないので、分岐を足して再試行可能な型へ寄せます。ストリーム途中のプロバイダエラーはステータスコードを持たない `APIError` として、接続断は httpx の例外として届きます。

ツール（関数呼び出し）を使うターンだけが `error` で終わる場合は、プロバイダ側のツール引数検証を疑います。`Tool call validation failed` や `tool_use_failed` は、モデルが返した引数がツールスキーマに合わないとしてプロバイダが拒否した状態で、`LlmToolSchemaError` として分類されます。ログの `tool_schema_retries` は利用可能な関数名を示してツール付きでやり直したステップ、`tool_schema_recoveries` は引き直しも拒否されてツールなしでやり直したステップです。`tool_schema_rejections` には拒否ごとの理由（`schema_mismatch`・`unknown_tool`・`unparsable_call`・`tool_choice_none`・`other`）、拒否文にあったツール名、そのステップで提示していたツール名が残り、メモなどのツールで手順がどこまで進んだかは `workspace_tool_results`（呼んだ順の `ツール名:status`）で追えます。`workspace_action_recoveries` は、カード無しで変更・提案を主張した回答を配信前に止め、ツール付きで一度訂正させた回数です。`unknown_tool` で提示していないツール名が出ていれば、モデルが一覧に無いツールを呼んでいます。未定義ツールの拒否は提示一覧とループ指示の整合を確認します。`schema_mismatch` なら、`enum` や `required` を足すのではなく、`services/llm_tool_schema.py` の緩和対象を確認し、値の正規化をハンドラ側（`services/chat_generation_tools.py`、`services/chat_generation_web_search.py`、`services/web_search.py`）へ寄せます（[ADR 0008](../decisions/0008-provider-safe-tool-schemas.md)）。

開始経路だけ正常で再生成・再接続だけ切れる場合は、`deploy/chatcore-ai.conf` の4つの SSE 経路が同じ location に入り、`proxy_buffering off` と長い `proxy_read_timeout` が適用されているか確認します。

1件のターンではなく傾向を見たいときは `python3 scripts/summarize_generation_telemetry.py logs/app.log` を使います。同じ `request_id` の複数行を1ターンに畳み（`request_id` が付いていない古いログでは、ターンを閉じた行だけを1ターンとして数え、その旨を出力の先頭に出します）、結果（`done` / `incomplete` / 終了イベントを出さずに終わった `error`）、初回パスの終了理由、生成 UI の状態と理由コード、継続・縮退・予算切れの発生率、分量の中央値を出します。チャットの出力に関わる変更では、変更前後で同じ入力を流し、`--baseline 変更前のログ` を付けて差分を見ます。率の差はポイント表示で、変更前後とも0件の指標は省略されます（`--all` で表示）。1つのログに複数回の試行が混ざる場合は `--since 2026-09-22T00:00:00` で範囲を絞ります。集計値だけを扱うため、本文・検索結果・ユーザー入力はこの出力に含まれません。

Skill が適用されない場合は、同じ `request_id` の `event=skill_selection` を確認します。`candidate_count` は当該経路で利用できる有効な Skill 数、`selected_skill_ids` と `selected_count` は本体へ渡す選択です。`fallback=true` の `reason` は `uncertain`、`invalid_response`、`llm_error`、`overflow`、`budget_error` のいずれかで、利用できる全候補へ戻したことを示します。`no_candidates` は候補が無くAIを呼ばなかった状態です。`duration_ms` と `input_tokens` は選択器の時間と入力見積もりです。生成本体の指標と混ぜず、リクエスト単位で併記してください。本文や生のプロバイダエラーはこのイベントへ追加しません。

## API 契約・フロント同期エラー

レスポンスのフィールドが実行時に欠ける、または TypeScript の型だけが古い場合は、`docs/knowledge/contracts-and-migrations.md` の同期手順を使います。生成ファイルを直接修正して一時的に型エラーを隠さないでください。
