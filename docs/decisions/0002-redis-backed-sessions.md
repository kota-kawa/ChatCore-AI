# ADR 0002: セッション本体を Redis に保存する

- 状態: Accepted
- 対象: `services/session_middleware.py`, `services/cache.py`, `services/email_auth_transaction.py`

## 背景

セッションには認証状態、検証コード、管理者フラグ、Passkey challenge など、ブラウザ Cookie にそのまま置くべきでない値が含まれます。複数ワーカーで同じセッションを扱う場合は、プロセス内メモリだけでは共有できません。Google OAuthのstateとPKCE verifier、メール認証コードを一般セッションへ混在させると、ログイン画面の並列リクエストや他機能の全体スナップショット保存で認証途中の状態が失われます。

## 判断

セッション本体は Redis の `session:<id>` に保存し、Cookie には署名済みの Redis 参照 ID だけを置きます。Google OAuthの一時状態は `google_oauth_transaction:<state>` に短いTTLで別保存し、stateをHttpOnly Cookieにも保持します。メール認証の一時状態は `email_auth_transaction:<id>` に短いTTLで別保存し、コードdigestと試行回数を専用HttpOnly Cookieに紐づけます。OAuthコールバックとメール認証コード検証はRedis上で一度だけ消費し、メール認証の試行回数更新には `WATCH`／`MULTI`／`EXEC` を使います。通常のセッション更新は読み込み時スナップショットとの楽観的排他を行い、認証成功でローテーションされた古いセッションの書き戻しを拒否します。Redis が利用できないときは、機密セッションや認証コードを署名 Cookie に退避せず、保存に失敗した Cookie を消去して安全側へ倒します。

## 影響

Redis はセッション、Google OAuth、メール認証トランザクションに必須の運用依存先になります。キャッシュやシングルフライトは用途ごとに劣化・フェイルオープンできますが、セッション維持、OAuth開始、メール認証コード送信は継続せず再試行・再認証が必要になります。Redis 障害経路と競合書き込みは、実 Redis だけでなく失敗・競合をモックした決定的なテストで検証します。
