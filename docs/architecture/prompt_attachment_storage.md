# プロンプト共有の画像添付ストレージ / Prompt-share image attachment storage

プロンプト共有の画像は、保存の前に必ず加工する。アプリはユーザーがアップロードした元ファイルを配信しない。
ファイルを完全にデコードし、ピクセル数が多すぎるものやアニメーションを拒否し、EXIF の向きを反映してメタデータを取り除いたうえで、
上限サイズ内の表示用 WebP と、それより小さいカード用 WebP を生成する。

Prompt-share images are processed before storage. The application never serves
the user-uploaded original: it fully decodes the file, rejects excessive pixel
counts and animation, applies EXIF orientation, removes metadata, and emits a
bounded display WebP plus a smaller card WebP.

`services.prompt_attachment_processing` は、保存先から意図的に独立させている。バイト列のバリアント（表示用・サムネイル用）を返すだけである。
`services.prompt_attachment_storage` の `PromptAttachmentStorage` が、プロンプト API から使われる永続化の境界になる。
その契約は次の 4 つの操作（識別子はそのまま記載）：

`services.prompt_attachment_processing` is deliberately independent of the
storage destination. It returns byte variants only. `PromptAttachmentStorage`
in `services.prompt_attachment_storage` is the persistence boundary used by the
prompt API:

- `save_variants(user_id, display_bytes, thumbnail_bytes)`
- `resolve_path(filename)` for the current local-serving implementation
- `delete_attachment(attachment)`
- `cleanup_unreferenced(active_attachments)`

現在の `LocalPromptAttachmentStorage` は、名前付き Docker ボリュームへアトミックに書き込む。
ユーザーごとの容量クォータのロックは、同じホスト上で同時に動く Blue/Green のコンテナ間で共有される。
定期的な孤立ファイルの突き合わせ（reconciler）にとって、正しい情報源は引き続きデータベースである。

The present `LocalPromptAttachmentStorage` writes atomically to the named
Docker volume. Its per-user quota lock is shared by the concurrently running
Blue/Green containers on the same host. The database remains the source of
truth for the periodic orphan reconciler.

`services.prompt_attachment_upload` は、加工と保存の境界を呼ぶ前に、ファイル名・MIME・シグネチャ・サイズの検証を担当する。
ブラウザの multipart エンドポイントと、MCP のプロンプト公開ツールの両方がこのサービスを使う。
MCP は Base64 入力を `publish_image_prompt_base64`（画像の data URL を含む）で、ChatGPT のファイル入力を `publish_image_prompt` で受け付ける。
後者は `_meta["openai/fileParams"]` で宣言される。ChatGPT のファイル入力は、HTTPS の `oaiusercontent.com` ホスト、または OpenAI 接頭辞つきの
署名付き Azure Blob ストレージアカウント（`oai<account>.blob.core.windows.net`）からだけ、リダイレクトなしで、同じ 5 MB のストリーミング上限のもとで取得する。
Azure のアカウントのパターンは、アップロード済みファイルと生成画像のストレージを、リージョンをまたいで扱えるようにしている。
任意のリモート URL や、OpenAI 接頭辞のない Azure Blob アカウントは取得しない。

`services.prompt_attachment_upload` owns filename, MIME, signature, and size
validation before calling the processing and storage boundaries. Both the
browser multipart endpoint and the MCP prompt-publishing tools use this service.
MCP accepts Base64 input through `publish_image_prompt_base64` (including an
image data URL) and required ChatGPT file inputs through `publish_image_prompt`,
declared through `_meta["openai/fileParams"]`. ChatGPT file inputs are fetched
only from its HTTPS `oaiusercontent.com` hosts or OpenAI-prefixed signed Azure
Blob storage accounts (`oai<account>.blob.core.windows.net`), without redirects,
and with the same 5 MB streaming limit. The Azure account pattern supports both
uploaded files and generated-image storage across regions. Arbitrary remote URLs
and Azure Blob accounts without the OpenAI prefix are not fetched.

ChatGPT が元の画像バイト列を持っているのに、会話内の画像をファイルパラメータとして渡せない、または Base64 が 1 回のツール呼び出しに収まらない場合のために、
MCP サーバーは上限つきの分割ステージングの流れも備える。`start_image_prompt_upload` は共有の添付ボリューム配下に、呼び出し元に紐づくセッションを作る。
`append_image_prompt_upload` は 1 つの Base64 文字列を順序つきの断片として保存し、`publish_chunked_image_prompt` は組み立てた値を検証して、
同じアップロードサービス経由で公開する。セッション作成時に宣言した Base64 の文字数があるため、未完了のアップロードは消費されない。
消費はアトミックなので、同時の追記や二重公開でセッションを再利用することもできない。セッションは 30 分で期限切れになり、
デコード後の画像データは最大 5 MB までで、明示的に取り消すこともでき、公開を試みたあとに削除される。
このステージングの実装は、複数ホストのストレージへ移行する際に、オブジェクトストレージの境界の内側へ移す必要がある。

When ChatGPT has the original image bytes but cannot expose a conversation image
as a file parameter or fit its Base64 value in one tool call, the MCP server also
supports a bounded chunk-staging flow. `start_image_prompt_upload` creates an
actor-bound session below the shared attachment volume,
`append_image_prompt_upload` stores ordered fragments of one Base64 string, and
`publish_chunked_image_prompt` validates and publishes the assembled value through
the same upload service. The expected Base64 character count declared at session
creation prevents an incomplete upload from being consumed; consumption is
atomic so concurrent append or duplicate publication cannot reuse the session.
Sessions expire after 30 minutes, accept at most 5 MB of decoded image data, can
be explicitly cancelled, and are deleted after the publication attempt. The staging
implementation must move behind the object-storage boundary during a multi-host
storage migration.

## 将来のオブジェクトストレージ移行 / Future object-storage migration

画像加工や投稿の流れを変えずに S3 互換のストレージや CDN へ移すには、同じストレージ契約を、オブジェクトキーと
トランザクション的なアップロード/確定の操作で実装する。添付ファイルの記述子のキー（`url`、`thumbnail_url`、`media_type`、`width`、`height`、`size_bytes`）は変えない。
そのうえで、ローカルのメディア用ルートを CDN の URL か短時間有効な署名付きリダイレクトに置き換え、
reconciler を、参照されていないオブジェクトキーの一覧取得と削除に変更する。
ローカルのファイルシステム版は意図的に複数ホストへ分散していないため、複数ホストへの水平スケールの前にこの移行が必須になる。

To move to S3-compatible storage/CDN without changing the image-processing or
posting flow, implement the same storage contract with object keys and a
transactional upload/finalize operation. Keep the attachment descriptor keys
(`url`, `thumbnail_url`, `media_type`, `width`, `height`, `size_bytes`) stable.
Then replace the local media route with a CDN URL or a short-lived signed
redirect and change the reconciler to list/delete unreferenced object keys.
The local filesystem variant is intentionally not distributed across hosts, so
that migration is required before multi-host horizontal scaling.
