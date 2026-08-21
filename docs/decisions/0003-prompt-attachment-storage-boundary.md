# ADR 0003: プロンプト添付画像の処理と保存先を分離する

- 状態: Accepted
- 対象: `services/prompt_attachment_processing.py`, `services/prompt_attachment_storage.py`
- 詳細: [`docs/architecture/prompt_attachment_storage.md`](../architecture/prompt_attachment_storage.md)

## 背景

アップロード画像の検査・変換と、ローカルファイルや将来のオブジェクトストレージへの保存は、異なる変更理由と障害特性を持ちます。保存先を処理コードに埋め込むと、CDN／オブジェクトストレージへの移行で投稿フローまで変更する必要があります。

## 判断

画像処理サービスはバイト列の表示用・カード用バリアントを返すだけにし、`PromptAttachmentStorage` を永続化の境界にします。現在のローカル実装の契約を保ったまま、将来の保存実装を差し替えられる形を維持します。

## 影響

処理の安全性テストと保存先の原子性・クリーンアップテストを分離できます。ローカル保存は単一ホストの制約を持つため、マルチホスト化の前にオブジェクトストレージ等への移行が必要です。保存契約の詳細は専門文書に集約します。
