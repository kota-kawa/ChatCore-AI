# Architecture Decision Records

このディレクトリには、将来の実装者が変更時に再評価できるよう、重要な技術判断と理由を短く残します。作業ログや単なる実装メモは追加しません。

## ADR 一覧

- [0001: バックエンドを API 契約の単一ソースにする](0001-backend-owned-api-contracts.md)
- [0002: セッション本体を Redis に保存する](0002-redis-backed-sessions.md)
- [0003: プロンプト添付画像の処理と保存先を分離する](0003-prompt-attachment-storage-boundary.md)
- [0004: DB スキーマ変更を Alembic の履歴で管理する](0004-alembic-schema-history.md)
- [0005: 認証IDの永続化境界を一般ユーザー機能から分離する](0005-auth-identity-persistence-boundary.md)
- [0006: 長時間チャットの最終回答を限定継続で回復する](0006-long-running-chat-completion-recovery.md)
- [0007: 調査ターンの回答契約を会話の末尾で渡す](0007-research-turn-answer-contract.md)

## 追加・更新の基準

判断が複数機能に影響する、後から覆すと移行コストが高い、またはセキュリティ・データ整合性に関わる場合に ADR を追加します。各 ADR には少なくとも「状態」「背景」「判断」「影響」を記載します。コードの詳細は `ARCHITECTURE.md` または専門文書へリンクし、ADR に複製しません。
