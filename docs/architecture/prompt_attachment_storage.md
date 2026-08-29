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
MCP accepts Base64 input (including an image data URL) and ChatGPT file inputs
declared through `_meta["openai/fileParams"]`. ChatGPT file inputs are fetched
only from its HTTPS `files.oaiusercontent.com` download host, without redirects,
and with the same 5 MB streaming limit. Arbitrary remote URLs are not fetched.

## Future object-storage migration

To move to S3-compatible storage/CDN without changing the image-processing or
posting flow, implement the same storage contract with object keys and a
transactional upload/finalize operation. Keep the attachment descriptor keys
(`url`, `thumbnail_url`, `media_type`, `width`, `height`, `size_bytes`) stable.
Then replace the local media route with a CDN URL or a short-lived signed
redirect and change the reconciler to list/delete unreferenced object keys.
The local filesystem variant is intentionally not distributed across hosts, so
that migration is required before multi-host horizontal scaling.
