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

The `image_file` input of `publish_image_prompt` is required at the top level. When an image was just generated in
ChatGPT, pass that image through the ChatGPT file input without model-side Base64 conversion or re-compression. A
successful result reports `image_attached: true` after the image has actually been saved. File-upload download URLs
are accepted only from ChatGPT's HTTPS file host, redirects are not followed, and streaming stops at the 5 MB limit.

Use `publish_image_prompt_base64` only when the image bytes are already available as Base64 (including a
`data:image/...;base64,...` value).
