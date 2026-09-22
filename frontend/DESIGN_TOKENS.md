# デザイントークン（色・角丸・影）

`frontend/public/static/css/base/variables.css` に定義されたトークンを、役割別に「どれを使うか」の観点でまとめた一覧です。値の正本は `variables.css` で、この文書は「今どう組まれているか」の参考資料です。色や形は固定ではなく、必要なら変えて構いません。変えるときは、新しい部品だけ別の色にするのではなく `variables.css` のトークンをライト・ダーク両方で更新して既存画面ごと揃え、この文書も同じコミットで直してください。避けたいのは、意図せず既存画面と浮いた見た目になることだけです。CSS の配置とカスケードの規約は `STYLING_STRATEGY.md`、タッチ操作や明度差などの UI 原則は `docs/knowledge/development_conventions.md` の「UI 実装規約」にあります。

## 全体の印象

- 全体の基本は白から薄い灰緑の面に、濃いグレーの文字、薄い黒の罫線、緑のアクセント。共有プロンプト詳細（`--shared-prompt-*`）だけは、プロンプト共有ページに合わせた青を使います。
- ダークテーマは `:root[data-theme="dark"]` で上書きされ、紺系の面（`#0f172a`／`#111827`）に各画面のアクセントを載せます。切替は `scripts/core/theme.ts` が `data-theme` 属性で行います。
- 角丸は 8〜14px、影は薄く広めで、輪郭は影ではなく罫線で作ります。

## 色トークン

| 役割 | トークン | ライト | ダーク | 使いどころ |
| --- | --- | --- | --- | --- |
| ブランド・アクセント | `--primary-color` / `--primary-hover` | `#19c37d` / `#15a86b` | 同じ | アイコン、罫線、淡い面、ダーク面の文字。白文字を載せる面や白地の文字にはコントラストが足りない（2.3:1）ので、その用途には `--primary-dark` を使っている |
| 白地の主操作 | `--primary-dark` / `--primary-dark-hover` | `#0f7a51` / `#0d6945` | 同じ | 白地のボタン面（白文字で 5.4:1）と白地のリンク文字。モーダルと設定画面のアクセントもこれを参照 |
| アクセントの淡い面 | `--primary-soft`、`--primary-subtle`、`--primary-alpha-06`〜`--primary-alpha-28`、`--primary-border` | `#e8f9f3`、緑の 6〜28% | 同じ | 選択中・ホバーの背景、緑の枝線。面の区別には `--border-default` を併用する |
| 文字 | `--text-dark` / `--text-secondary` / `--text-light` | `#1a1a1a` / `#6b7280` / `#ffffff` | `#e5e7eb` / `#9ca3af` / `#f9fafb` | 本文 17.4:1、副次 4.8:1。補助文字は不透明度ではなく `--text-secondary` |
| 面 | `--surface-primary` / `--surface-secondary` / `--surface-tertiary` / `--surface-sidebar` | `#ffffff` / `#f9fafb` / `#f2f5f3` / `#f7f8f7` | `#0f172a` / `#111827` / `#0b1220` / `#111827` | 面どうしの差は 1.05〜1.10:1 しかないので、区切りは必ず `--border-default` か余白で作る |
| 罫線 | `--border-default` / `--border-light` | 黒 8% / 5% | 灰青 28% / 22% | カード、区切り線、入力欄の枠 |
| 成功 | `--success-color` / `--success-strong` | `#15803d` / `#0f5132` | `#4ade80` / `#34d399` | 保存済み・完了の表示 |
| 失敗 | `--danger-color` / `--danger-hover` | `#dc2626` / `#b91c1c` | **上書きなし** | エラー表示だけに使う。ダーク面ではコントラスト 3.7:1 で不足するため、`--modal-danger`／`--settings-danger`（ダークで `#f87171`）のように文脈側トークンを使う |
| 情報 | `--info-color` / `--info-hover` | `#2563eb` / `#1d4ed8` | **上書きなし** | 現状は中立的な通知にだけ使っている。装飾に青を足すとアクセントが 2 色になる点に注意 |
| 中立ボタン | `--neutral-button` / `--neutral-button-hover` | `#6c757d` / `#5a646c` | **上書きなし** | 取り消し・閉じるなどの二次操作 |
| レガシー | `--secondary-color`、`--accent-color` | `#f5f5f5`、`#ff6b6b` | 上書きなし | 既存箇所の維持用。現在のアクセントは緑 1 色なので、赤系を足すなら意図的な変更として全体で揃える |

## 面ごとの文脈トークン

- **モーダル** `--modal-*`（面、罫線、文字、アクセント、危険色、フォーカスリング）。すべてのモーダルは `components/ui/modal_shell.tsx` と `public/static/css/components/modal_surface.css` を通し、ページは `--modal-accent`、`--modal-accent-hover`、`--modal-accent-text`、`--modal-accent-soft`、`--modal-focus-ring` だけを差し替えます。
- **設定画面** `--settings-*`。不透明な面と 1px 罫線で組む前提で、アクセント・危険色・フォーカスリングをライト／ダーク両方で持ちます。新しいページで独自の文脈トークンを作るときは、この構成（面／罫線／文字／アクセント／危険／フォーカス）が雛形として使えます。
- **チャット** `--chat-surface`、`--chat-surface-strong`、`--chat-surface-muted`、`--chat-border-soft`。半透明の白（ダークでは半透明の紺）で、背景の上に浮かべる面です。
- **公開プロンプト** `--ps-*`、**新規プロンプト** `--new-prompt-*`。ページ固有で、値は `--primary-*` を参照するか、`variables.css` 内で完結します。
- **共有プロンプト詳細** `--shared-prompt-accent`（リンク・カテゴリ: ライト `#185abc`／ダーク `#8ab4f8`）、`--shared-prompt-action`（主ボタン: `#1a73e8`／`#2563eb`）、`--shared-prompt-action-hover`（`#185abc`／`#1d4ed8`）。プロンプト共有ページの青系配色に揃え、ボタン文字と内側フォーカスリングは両テーマで `--text-light` を使います。
- **スクロールバー** `--scrollbar-*` が共通値で、ページ差は `--page-scrollbar-*` をページのスコープで定義して吸収します。

## 形と影

- 角丸: 入力欄・小ボタン `--radius-sm`（8px）、カード `--radius-m`〜`--radius-md`（12〜14px）、モーダル `--modal-radius`（14px）、ピル `--radius-full`。
- 影: 通常は `--shadow-sm`／`--shadow-md`、浮かせるパネルは `--shadow-panel`、主操作ボタンだけ `--shadow-button`（緑の影）。影で輪郭を作らず、罫線と組み合わせます。
- フォーカスリング: 白地は `--focus-ring`（緑 3px）、危険操作は `--shadow-danger-focus`、モーダルと設定は `--modal-focus-ring`／`--settings-focus-ring`。反転面（緑や濃色の面）では面と同じ色のリングだと見えなくなります。
- タップ領域: `--tap-target-min`（44px）。

## 新しい UI を作るときの目安

1. まず上の表から役割に合うトークンを探します。無ければ `variables.css` に追加し、ライトとダークの両方を同じコミットで定義します。
2. 基本のアクセントは緑、共有プロンプト詳細は青です。基本配色に揃えるなら、白地に白文字の面は `--primary-dark`、緑面の文字は `--text-dark` か `--modal-accent-text`（ダークの緑面用 `#062c1e`、6.6:1）が既存の組み合わせです。アクセントを変えたい場合は `--primary-*` を差し替えて全画面に反映させます。
3. ダーク面で使う色は、`:root[data-theme="dark"]` に上書きがあるトークンか、文脈トークン（`--modal-*`／`--settings-*`）から選ぶと崩れません。上書きの無い `--danger-color`、`--info-color`、`--neutral-button` をダーク面で使いたいときは、ダーク用の値を `variables.css` に足します。
4. 色は `variables.css` のトークン経由にすると、後から全体を変えやすくなります。既存ファイルには生の 16 進数が多数残っています（例: `public/memo/static/css/memo_form.css`）が、触った箇所だけ近いトークンへ置き換えれば十分で、範囲を超える一括置換は不要です。
5. 迷ったら既存の画面で同じ役割の要素がどのトークンを使っているかを `grep` で確かめ、それに揃えるのが一番早いです。
