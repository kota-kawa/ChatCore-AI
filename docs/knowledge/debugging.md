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
2. SSE の event 名、連番、`done`／`aborted`／`error` を確認する。本文が途中で止まっただけか、ジョブ自体が終了したかを区別する。
3. `services/chat_generation.py` のジョブ状態、キャンセル要求、イベント履歴、永続化の一度きり制御を確認する。
4. `blueprints/chat/messages.py` の再接続・ステータス・停止ルートと、`frontend/hooks/chat_page/use_home_page_generation_actions.ts` の Abort／再接続処理を照合する。
5. 外部 LLM の実通信の前に、生成ストリームをモックして「接続切断」「再接続」「途中停止」「プロバイダエラー」をテストする。

完了通知と停止通知の競合で二重保存しやすいため、永続化処理をルートへ追加せず `ChatGenerationJob` の一度きり制御を通します。フロントの表示だけを直す場合も、サーバーが返すイベント契約を先に確認します。

## API 契約・フロント同期エラー

レスポンスのフィールドが実行時に欠ける、または TypeScript の型だけが古い場合は、`docs/knowledge/contracts-and-migrations.md` の同期手順を使います。生成ファイルを直接修正して一時的に型エラーを隠さないでください。
