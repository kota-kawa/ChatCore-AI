# API 契約と DB migration の同期

## API 契約の流れ

バックエンドの Pydantic モデルがリクエスト／レスポンス契約の単一ソースです。`scripts/generate_frontend_zod_schemas.py` がモデルを収集し、`frontend/types/generated/api_schemas.ts` を生成します。

```text
services/request_models.py
services/response_models.py
        │
        └─ scripts/generate_frontend_zod_schemas.py
                    │
                    └─ frontend/types/generated/api_schemas.ts
```

### 変更手順

1. バックエンドの Pydantic request/response model と、必要ならルートのシリアライズ処理を変更する。
2. `npm --prefix frontend run generate:api-schemas` を実行する。
3. 生成差分を確認し、生成ファイルを手編集していないことを確認する。
4. `npm --prefix frontend run typecheck` と変更箇所に直接関係する logic/component test を実行する。
5. レガシー応答の吸収や外部入力の防御が必要なら、`frontend/lib/chat_page/api_contract.ts` などの正規化層を更新する。

### よくある失敗

- Pydantic だけ変更して生成コマンドを実行しない。
- `frontend/types/generated/api_schemas.ts` を直接編集し、次の生成で差分を失う。
- API の JSON 形状を変えたのに、SSE のイベント payload や正規化関数を確認しない。
- 型検査だけで済ませ、HTTP エラー、空値、後方互換の実行時テストを追加しない。

## DB migration の流れ

DB の変更は、適用済み履歴を保つ新しい Alembic revision として追加します。

1. 既存の head と対象テーブル・インデックスを確認する。
2. 新しい migration を追加し、upgrade と downgrade の責務を明確にする。
3. 既存 migration を書き換えず、アプリ起動時の暗黙 SQL にスキーマ変更を隠さない。
4. モデル／API の変更があれば、契約生成と対象ルートテストも同じ変更に含める。
5. 直接 SQL の `db/performance_indexes.sql` が必要なケースでも、通常のスキーマ履歴を Alembic と二重管理しない。

### 検証時の注意

- migration は DB の状態を変えるため、テスト対象を限定し、既存のローカル DB に適用する前に対象と順序を確認する。
- 一意制約、外部キー、soft delete、ページング用インデックスは、migration の SQL だけでなくルートの所有者確認・競合時のエラー変換まで確認する。
- 生成スキーマと migration を混同しない。前者は API の型、後者は永続化構造の履歴です。
