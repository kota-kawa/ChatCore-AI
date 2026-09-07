# ADR 0001: バックエンドを API 契約の単一ソースにする

- 状態: Accepted
- 対象: `services/request_models.py`, `services/response_models.py`, `scripts/generate_frontend_zod_schemas.py`

## 背景

バックエンドと Next.js フロントエンドが同じ API を利用するため、リクエスト／レスポンス型を別々に手書きすると、フィールド追加や nullable の変更が実行時まで検知できません。

## 判断

契約はバックエンドの Pydantic model で定義し、生成スクリプトでフロントエンド Zod スキーマへ反映します。生成物 `frontend/types/generated/api_schemas.ts` は手編集しません。複雑なレガシー応答の吸収は、生成物ではなくフロントエンドの正規化層で行います。

## 影響

バックエンドモデル変更時に生成コマンドとフロントエンドの型検査を実行する必要があります。一方、契約の二重管理を避けられ、API の形状変更をレビューで追跡できます。手順は `docs/knowledge/contracts-and-migrations.md` にあります。

## 更新履歴 / Update log

### 2026-09-07: チャット系ホットパスを生成 Zod スキーマで検証する

`frontend/lib/chat_page/api_contract.ts` は生成物と無関係に手書きガード（`isUnknownRecord` / `optionalString` / `asBoolean` など）で型を確認していたため、生成 Zod スキーマと実際の検証が黙って乖離しうる状態でした。新設した `frontend/lib/chat_page/generated_contract.ts` を橋渡し層として、以下のペイロードは生成 Zod スキーマのフィールド定義で検証します。

| ペイロード / Payload | 生成スキーマ / Generated schema |
| --- | --- |
| チャット応答 (`normalizeChatResponsePayload`) | `ChatJsonResponseSchema`（`response` / `error`） |
| 生成状況 (`normalizeGenerationStatusPayload`) | `ChatGenerationStatusResponseSchema`（全項目） |
| 履歴メッセージ (`normalizeChatHistoryMessages`) | `ChatHistoryMessageSchema`（`id` / `message` / `sender` / `timestamp`） |
| 履歴ページネーション (`normalizeChatHistoryPagination`) | `ChatHistoryPaginationSchema`（全項目） |
| 履歴応答 (`normalizeChatHistoryPayload`) | `ChatHistoryResponseSchema`（`error`） |
| 共有リンク (`normalizeShareChatRoomPayload`) | `ShareChatRoomResponseSchema`（`share_url`） |

判断は変えていません。契約はバックエンドの Pydantic model が正本であり、生成物は手編集しません。変わったのは「フロントエンドの正規化層が、契約が所有するフィールドについては生成物を経由して検証する」点だけです。

- 検証は必ず `safeParse` で行い、失敗時は従来と同じ既定値（`undefined` / `false` / `null`）へ落とします。UI を壊さないため、生成スキーマの厳格さでアプリを締めることはしません。
- ペイロード全体を `parse` しません。`detail` や `params` のような読まないフィールドが壊れていても、読む項目が落ちないようにフィールド単位で検証します。同様に `messages` 配列も要素単位で検証し、1 件の不正で全件が落ちないようにします。
- Pydantic model に宣言のない追加キー（`room_mode`、`room_title`、`parts` / `message_parts`、`attached_file_names`、`version_index` / `version_count`、`sibling_ids`）と、レスポンスモデルを持たないチャットルーム一覧（`blueprints/chat/rooms.py` が dict を直接返す）は、引き続きフロントエンドの正規化層が扱います。該当箇所には対応する生成スキーマ名と、まだ使えない理由をコメントで残しています。
- 生成 UI アーティファクト・対話ボタン・Web 検索画像の正規化は、サンドボックス配信や URL スキーム制限といったフロントエンド固有の規則を含むため、契約側へは移せません。

したがって、バックエンドの Pydantic model を変更したら `npm run generate:api-schemas` を実行するという AGENTS.md の要求は、これまでよりも重要になります。再生成を忘れると、上表のフィールドはチャット画面で黙って `undefined` / 既定値に落ち、フォールバックのテスト（`frontend/tests/api_contract.test.ts`）でも検知できません。

English summary: the chat hot path no longer type-checks these payloads by hand. `frontend/lib/chat_page/generated_contract.ts` validates the contract-owned fields of the payloads listed above with the generated Zod schemas, always via `safeParse` and always falling back to the previous defaults. Fields and endpoints that the backend still returns outside its Pydantic models (extra keys, and the chat-room list, which has no response model) keep the frontend normalization layer, each annotated with the generated schema it would correspond to. Because of this, regenerating the schemas after a Pydantic model change is now load-bearing: a stale generated file makes those fields silently fall back to `undefined` on the chat screen.
