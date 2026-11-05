# Prompt-share image attachment storage

Prompt-share images are processed before storage. The application never serves
the user-uploaded original: it fully decodes the file, rejects excessive pixel
counts and animation, applies EXIF orientation, removes metadata, and emits a
bounded display WebP plus a smaller card WebP.

`services.prompt_attachment_processing` is deliberately independent of the
storage destination. It returns byte variants only. `PromptAttachmentStorage`
in `services.prompt_attachment_storage` is the persistence boundary used by the
prompt API:

- `save_variants(user_id, display_bytes, thumbnail_bytes)`
- `resolve_path(filename)` for the current local-serving implementation
- `delete_attachment(attachment)`
- `cleanup_unreferenced(active_attachments)`

The present `LocalPromptAttachmentStorage` writes atomically to the named
Docker volume. Its per-user quota lock is shared by the concurrently running
Blue/Green containers on the same host. The database remains the source of
truth for the periodic orphan reconciler.

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

## Future object-storage migration

To move to S3-compatible storage/CDN without changing the image-processing or
posting flow, implement the same storage contract with object keys and a
transactional upload/finalize operation. Keep the attachment descriptor keys
(`url`, `thumbnail_url`, `media_type`, `width`, `height`, `size_bytes`) stable.
Then replace the local media route with a CDN URL or a short-lived signed
redirect and change the reconciler to list/delete unreferenced object keys.
The local filesystem variant is intentionally not distributed across hosts, so
that migration is required before multi-host horizontal scaling.
