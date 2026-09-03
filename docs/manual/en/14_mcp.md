---
title: MCP integrations
locale: en
---

# MCP integrations

## What MCP is

Model Context Protocol integrations let supported AI features connect to configured tools or data sources. Tool identifiers and schemas use stable English machine-readable names even when the interface is displayed in Japanese.

## Connect an integration

Open the relevant settings, review the requested access, and complete the provider's authorization flow. Only connect services you trust and grant the minimum access required.

## Disconnect and troubleshoot

Disconnect an integration from Settings when it is no longer needed. If authorization fails, confirm that the provider account and redirect flow are still valid, then retry without sharing authorization codes or client secrets.

## Publish image prompts

The `publish_prompt` tool accepts `media_type` values `text` and `image`. For an image prompt, use
`publish_image_prompt` for a ChatGPT file input or `publish_image_prompt_base64` when the actual image bytes are
already available as Base64. `publish_prompt` also requires an image input when `media_type=image`. Remote image
URLs are not fetched. Images go through the same validation, metadata stripping, and WebP normalization as browser
uploads before they are saved.

The `image_file` input of `publish_image_prompt` is required at the top level. When ChatGPT exposes the current image
as a file, pass it through that input without model-side Base64 conversion or re-compression. A successful result
reports `image_attached: true` after the image has actually been saved. File-upload download URLs
are accepted from ChatGPT's `oaiusercontent.com` subdomains or OpenAI-prefixed signed Azure Blob storage accounts
(`oai<account>.blob.core.windows.net`). Arbitrary Azure Blob and remote URLs are not fetched; redirects are not
followed, and streaming stops at the 5 MB limit.

Use `publish_image_prompt_base64` only when the image bytes are already available as Base64 (including a
`data:image/...;base64,...` value).

If a generated conversation image cannot be bound to `image_file` and the complete Base64 value does not fit in one
tool call, use `start_image_prompt_upload` before asking the user to attach the file again. Split one complete Base64
string into consecutive fragments after passing its exact character count to the start tool. Send fragments no
longer than the returned limit in order with
`append_image_prompt_upload`, and finish with `publish_chunked_image_prompt`. Do not encode separate binary chunks
independently. An incomplete finalize attempt keeps the session available to resume. The temporary upload is bound
to the authenticated user and client, expires after 30 minutes, can be removed with `cancel_image_prompt_upload`,
and is a best-effort fallback only when ChatGPT can access the original bytes. It is
deleted after image validation or publication starts. Reattachment is still required if ChatGPT cannot access the
original image bytes at all. If an existing MCP connection cached the old tool list, disconnect and reconnect
Chat-Core before retrying.
