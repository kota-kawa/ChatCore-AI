# 0016: マイコンテキストの事実に本人の確認状態を持たせる

## 状態

採用。

## 背景

`context_facts` には「本人が確かめた事実か」「いつ確かめたか」を表す列がありませんでした。出所は `source_kind`（`manual`／`chat`／`mcp`／`import`）だけで、`updated_at` は DB のトリガーがあらゆる UPDATE（埋め込みの保存を含む）で進めるため、確認時刻としては使えません。抽出候補（`context_fact_candidates`）が持つ `confidence` も、承認で事実になるときに失われていました。

MCP の `save_context_fact` は本人の承認なしに active な事実を作れます。チャットはその事実と、本人が確かめた事実を同じ重みで参照していたため、両者が食い違ったときに古い外部書き込みを根拠にする余地がありました。

## 判断

- `context_facts` に `confidence`（0〜1、NULL 可）と `last_confirmed_at`（NULL 可）を追加します。
- `confidence` は抽出時の確信度です。候補の承認で候補の値を引き継ぎ、本人が書いた事実・MCP・import では NULL のままにします。確認済みかどうかは `confidence` では表しません。
- `last_confirmed_at` は本人が最後に確かめた時刻で、NULL は未確認です。出所と組み合わせて読みます。
  - 抽出由来（`chat`）: 承認時に現在時刻。`confidence` は候補の値。
  - 本人の手入力（`manual`）: 作成時に現在時刻。`confidence` は NULL。
  - MCP 由来（`mcp`）・import 由来（`import`）: NULL。import ファイルの `last_confirmed_at` と `confidence` は書き出し用の記録であり、取り込みでは使いません。
- 更新規則: タイトル・内容・種類の編集は、Web UI（本人）なら現在時刻に、MCP なら NULL に戻します。外部クライアントによる書き換えは本人が見ていないためです。重要度の変更、無効化・復元、埋め込みの保存は `last_confirmed_at` を変えません。
- 既存行は移行で埋めます。`chat` は承認済み候補の `confidence` と承認時刻（候補が残っていなければ `created_at`）、`manual` は `created_at`、`mcp`・`import` は NULL です。バックフィルは `updated_at` を動かしません。
- チャットの検索結果と概観には、事実ごとに `source_kind`、`confirmed`（`last_confirmed_at` が非 NULL か）、`last_confirmed_at`（日付）を渡します。プロンプト文言は変えず、読み手（モデル）が根拠の強さを判断する材料だけを渡します。
- 事実の自動失効（一定期間で deprecate）はしません。確認からの経過日数は事実の種類で意味が違い（好みは長く続き、進行中の案件は数日で古くなる）、一律のしきい値は正しい事実を黙って外すためです。失効させるかどうかの判断は本人に残し、読み手には日付を渡します。

## 影響

- `ContextFactResponse` に `confidence` と `last_confirmed_at` が増えます。画面はこの変更では変えません。
- MCP の `get_personal_context`・`search_context` の応答にも同じ項目が含まれ、外部クライアントも確認状態を読めます。
- チャットの検索結果に未確認事実が含まれる場合、そのターンは「常に承認」の自動実行条件を満たしません。事実自体は回答の根拠から除かず、書き込み提案は通常の承認カードで利用者が確認します。
- `last_confirmed_at` を `updated_at` の代わりに並び順やカーソルへ使いません。
- ルーム内の会話記憶 `memory_facts` は別系統で、この判断の対象外です。
- 下位互換のため両列は NULL 許容の追加です。downgrade は列を削除するため確認履歴を失い、実行前に論理バックアップが必要です。
