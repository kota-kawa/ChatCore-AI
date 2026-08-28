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

The `publish_prompt` tool accepts `media_type` values `text` and `image`. To include a reference image,
send `image_base64` with a PNG, JPEG, WebP, or GIF encoded in Base64 (up to 5 MB decoded). You may also
provide `image_filename` and `image_mime_type`; a `data:image/...;base64,...` value is supported as well.
Remote image URLs are not fetched. Images go through the same validation, metadata stripping, and WebP
normalization as browser uploads before they are saved.
