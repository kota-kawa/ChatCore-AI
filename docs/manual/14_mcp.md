# MCP連携

Chat-Coreは、MCP対応のAIサービスから公開プロンプト共有へ投稿できます。

接続先URLは `https://chatcore-ai.com/mcp` です。接続時はブラウザでChat-Coreへログインし、
「公開プロンプトを投稿する」権限を許可します。投稿は直ちに公開されます。

初版ではテキストプロンプトとSKILLを投稿できます。画像添付、チャット実行、下書き投稿には対応していません。
SKILLに含めたコードは保存・表示のみで、Chat-Core上で実行されません。

MCP経由の投稿は1時間に10件、24時間に50件までです。設定画面の「セキュリティ」から、接続済みAIサービスをいつでも解除できます。

運用者は `MCP_ENABLED=true`、正規の公開URLを指定する `MCP_PUBLIC_BASE_URL`、Fernet鍵をカンマ区切りで指定する
`MCP_OAUTH_ENCRYPTION_KEYS` を設定して有効化します。ブラウザ型MCPクライアントを許可する場合は、
`MCP_ALLOWED_ORIGINS` に信頼するOriginを明示します。

本番の `.env` には次の値を設定してから再デプロイします。`.env` はGitへ追加しないでください。

```dotenv
MCP_ENABLED=true
MCP_PUBLIC_BASE_URL=https://chatcore-ai.com
MCP_OAUTH_ENCRYPTION_KEYS=<Fernet鍵>
MCP_ALLOWED_ORIGINS=
```

Fernet鍵は `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` で生成できます。
`MCP_ALLOWED_ORIGINS` が空の場合は `MCP_PUBLIC_BASE_URL` と同じOriginだけを許可します。鍵をローテーションする場合は、
新しい鍵を先頭、以前の鍵を後ろにしてカンマ区切りで指定します。
