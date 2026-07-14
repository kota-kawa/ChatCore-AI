# MCP連携

Chat-Coreは、MCP対応のAIサービスから公開プロンプト共有へ投稿できます。

接続先URL（正規）は `https://chatcore-ai.com/mcp` です。`www.` 付きでも接続できますが、
OAuthメタデータはすべてこの正規ホストを指すため、`www.` なしの登録を推奨します。接続時はブラウザで
Chat-Coreへログインし、「公開プロンプトを投稿する」権限を許可します。投稿は直ちに公開されます。

MCPクライアント（ChatGPTなど）はRFC 8707の `resource` インジケータを送らない場合があります。
その場合も接続先ホストを正規リソースとみなして受け付けます。

初版ではテキストプロンプトとSKILLを投稿できます。画像添付、チャット実行、下書き投稿には対応していません。
SKILLに含めたコードは保存・表示のみで、Chat-Core上で実行されません。

MCP経由の投稿は1時間に10件、24時間に50件までです。設定画面の「セキュリティ」から、接続済みAIサービスをいつでも解除できます。

自動接続（DCR）が失敗し、OAuth認証情報を手動入力できるAIサービスを連携する場合は、Chat-Coreへログイン後、
設定画面の「セキュリティ」から「AIサービス連携用認証情報」を発行します。連携先サービスで正規の接続先URLを指定し、
そのサービスが指定するコールバックURL（リダイレクトURI）を入力してから、詳細設定に表示されたクライアントIDとクライアントシークレットを入力してください。
認証情報はユーザー専用で、シークレットは発行時だけ表示されます。コールバックURLは発行後に変更できないため、変更するときは新しい認証情報を発行し、不要になった認証情報を削除してください。

運用者は `MCP_ENABLED=true`、正規の公開URLを指定する `MCP_PUBLIC_BASE_URL`、Fernet鍵をカンマ区切りで指定する
`MCP_OAUTH_ENCRYPTION_KEYS` を設定して有効化します。ブラウザ型MCPクライアントを許可する場合は、
`MCP_ALLOWED_ORIGINS` に信頼するOriginを明示します。DNSリバインディング保護で許可するHostは
`MCP_ALLOWED_HOSTS`（カンマ区切り）で上書きできます。未設定時は `MCP_PUBLIC_BASE_URL` のホストと
その `www.`／apex のもう一方を自動的に許可します。

公開されるOAuth登録・認可エンドポイントにはIP単位の制限と本文サイズ上限を適用します。標準値は
登録が1時間20回、認可が10分30回、本文64KiBです。CIMD（Client ID Metadata Document）の外部取得は
専用の最大4並列executorで行い、成功・失敗を含め最大256件までキャッシュします。必要に応じて次の環境変数で
調整してください。

本番の `.env` には次の値を設定してから再デプロイします。`.env` はGitへ追加しないでください。

```dotenv
MCP_ENABLED=true
MCP_PUBLIC_BASE_URL=https://chatcore-ai.com
MCP_OAUTH_ENCRYPTION_KEYS=<Fernet鍵>
MCP_ALLOWED_ORIGINS=
MCP_ALLOWED_HOSTS=
MCP_DCR_RATE_LIMIT_PER_HOUR=20
MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES=30
MCP_MACHINE_MAX_BODY_BYTES=65536
MCP_CIMD_CACHE_ENTRIES=256
MCP_CIMD_MAX_CONCURRENT_FETCHES=4
```

Fernet鍵は `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` で生成できます。
`MCP_ALLOWED_ORIGINS` が空の場合は `MCP_PUBLIC_BASE_URL` と同じOriginだけを許可します。鍵をローテーションする場合は、
新しい鍵を先頭、以前の鍵を後ろにしてカンマ区切りで指定します。
