# Architecture details index

`ARCHITECTURE.md` でシステム全体の境界を確認した後、作業対象に対応する文書だけを参照します。ここには構造情報を置き、デバッグ手順は `docs/knowledge/`、判断理由は `docs/decisions/` に置きます。

## 構造マップ

- [Frontend feature map](frontend_feature_map.md)
- [Backend route map](backend_route_map.md)
- [Data model](data_model.md)
- [Deployment and operations](deployment_and_operations.md)
- [Testing map](testing_map.md)
- [Prompt attachment storage](prompt_attachment_storage.md)
- [System design deep dive](system_design_deep_dive.md)

`system_design_deep_dive.md` は、機能単位の設計意図（AIエージェント、生成UI、クォータ、代表的な上限、シナリオ、用語）を補う長文の詳細です。`ARCHITECTURE.md` と重複する記述は置かず、該当章へのリンクにしています。

各マップは実装の概略と参照先を示します。URL の正確な定義、DB の列、コンポーネントの実装詳細はコードと migration を正本とし、変更時に該当マップも更新します。
