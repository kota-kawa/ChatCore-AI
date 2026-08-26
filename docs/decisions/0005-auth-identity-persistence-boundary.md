# ADR 0005: 認証IDの永続化境界を一般ユーザー機能から分離する

- 状態: Accepted
- 対象: `services/repositories/auth_identity_repository.py`, `services/users.py`, `user_auth_providers`

## 背景

認証プロバイダー情報を`users`から`user_auth_providers`へ正規化した後も、一般ユーザーRepositoryに残ったGoogle認証処理が削除済みの`users`列へ書き込み、OAuthコールバックが失敗しました。認証と無関係なDB層変更に認証の暗黙契約が混在していたため、通常のモック中心ルートテストでは不整合を検出できませんでした。

## 判断

メール・Google・Passkeyが使用するユーザー検索、作成、プロバイダー連携、認証済み更新を`AuthIdentityRepository`へ集約します。プロバイダー情報の正本は`user_auth_providers`のみとし、`users`へ重複して書き込みません。一般ユーザー機能の`UserRepository`は認証情報を読み書きしません。

認証専用Repositoryのテストではハンドラのモックだけでなく、生成するSQLの対象テーブルと現行SQLAlchemyモデルでのユーザー作成を検証します。これにより、将来のスキーマ変更で認証契約がずれた場合はデプロイ前に失敗させます。

## 影響

認証IDや`users`／`user_auth_providers`の構造を変更する場合は、認証専用Repositoryとその契約テストを同時に更新する必要があります。チャット、プロフィール表示、既定タスクなど一般ユーザー機能の変更からは認証永続化へ直接アクセスしません。
