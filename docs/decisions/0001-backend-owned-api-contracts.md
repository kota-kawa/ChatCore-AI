# ADR 0001: バックエンドを API 契約の単一ソースにする

- 状態: Accepted
- 対象: `services/request_models.py`, `services/response_models.py`, `scripts/generate_frontend_zod_schemas.py`

## 背景

バックエンドと Next.js フロントエンドが同じ API を利用するため、リクエスト／レスポンス型を別々に手書きすると、フィールド追加や nullable の変更が実行時まで検知できません。

## 判断

契約はバックエンドの Pydantic model で定義し、生成スクリプトでフロントエンド Zod スキーマへ反映します。生成物 `frontend/types/generated/api_schemas.ts` は手編集しません。複雑なレガシー応答の吸収は、生成物ではなくフロントエンドの正規化層で行います。

## 影響

バックエンドモデル変更時に生成コマンドとフロントエンドの型検査を実行する必要があります。一方、契約の二重管理を避けられ、API の形状変更をレビューで追跡できます。手順は `docs/knowledge/contracts-and-migrations.md` にあります。
