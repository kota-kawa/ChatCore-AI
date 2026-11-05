# 公開投稿の添付画像保存 / Prompt-share image attachment storage

公開投稿の画像は保存前に完全にデコードし、過大な画素数とアニメーションを拒否します。EXIFの向きを適用してメタデータを除き、容量制限内の表示用WebPと小さなカード用WebPを作ります。アップロードされた原本は配信しません。

Prompt-share images are processed before storage. The application never serves
the user-uploaded original: it fully decodes the file, rejects excessive pixel
counts and animation, applies EXIF orientation, removes metadata, and emits a
bounded display WebP plus a smaller card WebP.

画像処理は保存先に依存せず、バイト列の派生画像だけを返します。投稿APIはPromptAttachmentStorageを境界とし、以下の保存・解決・削除・未参照画像掃除の操作を使います。

`services.prompt_attachment_processing` is deliberately independent of the
storage destination. It returns byte variants only. `PromptAttachmentStorage`
in `services.prompt_attachment_storage` is the persistence boundary used by the
prompt API:

- `save_variants(user_id, display_bytes, thumbnail_bytes)`
- `resolve_path(filename)` for the current local-serving implementation
- `delete_attachment(attachment)`
- `cleanup_unreferenced(active_attachments)`

現在は名前付きDockerボリュームへ原子的に保存します。利用者ごとの容量確認ロックは、同じホストのBlue/Greenコンテナ間で共有します。定期的な未参照ファイルの照合ではDBを正本とします。

The present `LocalPromptAttachmentStorage` writes atomically to the named
Docker volume. Its per-user quota lock is shared by the concurrently running
Blue/Green containers on the same host. The database remains the source of
truth for the periodic orphan reconciler.

アップロードサービスがファイル名・MIME・シグネチャ・サイズを検証し、ブラウザーのmultipartとMCPの両方から利用します。MCPはBase64とChatGPTのファイル引数に対応します。ファイル取得先はHTTPSのoaiusercontent.comまたはOpenAI用のoai接頭辞付きAzure Blobアカウントに限定し、リダイレクトせず5MBのストリーム上限を適用します。任意URLや他のAzureアカウントからは取得しません。

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

画像をファイル引数にできず、Base64が1回のツール呼び出しに収まらない場合は分割アップロードを使います。開始時に利用者へ紐付けたセッションを共有ボリュームに作り、順序付き断片を保存してから同じアップロードサービスで検証・公開します。予定文字数で不完全なデータの消費を防ぎ、原子的な消費で並行追記や二重公開を防ぎます。期限は30分、デコード後の上限は5MBで、明示キャンセルと公開試行後の削除に対応します。複数ホスト化するときは、この一時保存もオブジェクト保存の境界へ移します。

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

## 将来のオブジェクト保存への移行 / Future object-storage migration

画像処理や投稿の流れを変えずにS3互換保存/CDNへ移るには、同じ契約をオブジェクトキーとトランザクションを持つアップロード・確定処理で実装します。添付の記述キー（url、thumbnail_url、media_type、width、height、size_bytes）は保ちます。ローカル配信をCDNまたは短命な署名付きリダイレクトに置き換え、照合処理も未参照キーの一覧・削除へ移します。現在のファイル保存はホストをまたがないため、複数ホストへの水平拡張前にこの移行が必要です。

To move to S3-compatible storage/CDN without changing the image-processing or
posting flow, implement the same storage contract with object keys and a
transactional upload/finalize operation. Keep the attachment descriptor keys
(`url`, `thumbnail_url`, `media_type`, `width`, `height`, `size_bytes`) stable.
Then replace the local media route with a CDN URL or a short-lived signed
redirect and change the reconciler to list/delete unreferenced object keys.
The local filesystem variant is intentionally not distributed across hosts, so
that migration is required before multi-host horizontal scaling.
