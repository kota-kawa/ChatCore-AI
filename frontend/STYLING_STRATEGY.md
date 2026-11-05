# スタイリング方針 / Styling Strategy

- スタイリングの主軸は **CSS カスタムプロパティ + 分割した CSS ファイル**。
- Primary styling axis: **CSS custom properties + modular CSS files**.
- `:root` のトークンは `public/static/css/base/variables.css` だけで定義する。
- `:root` tokens are defined only in `public/static/css/base/variables.css`.
- 色・角丸・影のトークンと、その選び方の規則は `DESIGN_TOKENS.md`（日本語）にまとめてある。`variables.css` の値を変えるときは、同じコミットでこの文書も更新する。
- The colour, radius and shadow tokens, and the rules for choosing them, are documented in `DESIGN_TOKENS.md` (Japanese). Change a value in `variables.css` and that document in the same commit.
- ページ単位の見た目の違い（たとえばスクロールバー）は、`:root` のトークンを複製せず、`--page-scrollbar-*` のようなページ専用の変数で表す。
- Page-level visual differences (for example scrollbars) use page-scoped variables such as `--page-scrollbar-*`, not duplicated `:root` tokens.
- Bootstrap の CSS は読み込まない。残しているのは npm 経由の `bootstrap-icons` だけ。
- Bootstrap's CSS is not loaded. Only `bootstrap-icons` remains, via npm.
- 管理画面は Tailwind のユーティリティクラスを使わなくなった。最後の利用箇所は `components/settings/prompt_category_select.tsx`（`min-w-0`、`flex-1`、`truncate`）。`styles/globals.css` は今も Tailwind を import していて、その base リセット（preflight）が全ページに効くため、依存を外すと全体の基本スタイルが変わる。外すなら別の変更として行う。Tailwind のユーティリティを新しく足さない。
- The admin pages no longer use Tailwind utility classes; the last user is `components/settings/prompt_category_select.tsx` (`min-w-0`, `flex-1`, `truncate`). `styles/globals.css` still imports Tailwind, which also brings its base reset (preflight) to every page, so removing the dependency changes base styles app-wide and needs its own change. Do not add new Tailwind utilities.

## スタイルシートの読み込み場所 / Where a stylesheet is loaded

外部 CSS ファイルを読み込む経路は次の 2 つ。
External CSS files enter the app through two loading paths:

1. **グローバルバンドル** — `pages/_app.tsx` の先頭にある `import "...css"`。Webpack が import 順に連結し、Next が全ルート共通の `<link>` 群として出力する。
2. **ページの `<link>`** — そのページ自身がスタイルシートの link を描画する。既存のページは `next/head`（`<SeoHead>` の子）を使う。クライアント遷移で入るページは `<link rel="stylesheet" href="..." precedence="..." />` を直接描画でき、React がスタイルシートを管理し、読み込み完了を待ってからページを表示する。`frontend/public/` 配下のファイルは同じ URL パスで配信されるため、`public/static/css/pages/docs/docs.css` は `/static/css/pages/docs/docs.css` になる。

1. **The global bundle** — `import "...css"` statements at the top of `pages/_app.tsx`. Webpack concatenates them in import order and Next emits them as one `<link>` set on every route.
2. **A page `<link>`** — the owning page renders its stylesheet link. Existing pages use `next/head` (as a child of `<SeoHead>`). A page entered through client navigation can render `<link rel="stylesheet" href="..." precedence="..." />` directly so React manages the stylesheet and waits for it before displaying the page. Files under `frontend/public/` are served at the matching URL path, so `public/static/css/pages/docs/docs.css` is `/static/css/pages/docs/docs.css`.

ページ専用の新しい CSS は 2 の形を使う。本当に共有するものでない限り、`_app.tsx` には何も足さない。
New page-only CSS should use form 2. Nothing new should be added to `_app.tsx` unless it is genuinely shared.

認証ゲートの `components/auth/auth_gateway_modules/styles/auth_gateway_global_styles.tsx` は、`<style jsx global>` でページ固有 CSS を埋め込む。これは外部ファイルの読み込みとは別の経路であり、上の 2 種類には数えない。
The auth gateway embeds page-specific CSS with `<style jsx global>` in `components/auth/auth_gateway_modules/styles/auth_gateway_global_styles.tsx`. This embedded style is separate from the two external-file loading paths above.

### `_app` から外す前に守るカスケード規則 / Cascade rule you must respect before moving a file out of `_app`

`next/document` の `<Head>` は、ページ自身の `next/head` の子を、バンドルされた `_app` の CSS link **より前**に出力する（`Head.render()` は `head` を出してから `getCssLinks(files)` を出す）。つまりファイルを `_app` から外すとカスケード上は後ろではなく**前**に動き、移動後はグローバルバンドルに残っているすべてのルールが、同じ強さの競合に勝つようになる。クライアント遷移では注入される `<link>` が `<head>` の末尾に入るため、位置は安定すらしない。
`next/document`'s `<Head>` renders the page's own `next/head` children **before** the bundled `_app` CSS links (`Head.render()` emits `head` and then `getCssLinks(files)`). So moving a file out of `_app` moves it **earlier** in the cascade, not later: after the move, every rule still in the global bundle wins any tie against it. On client-side navigation the injected `<link>` lands at the end of `<head>` instead, so the position is not even stable.

したがって、ファイルを `_app.tsx` から外してよいのは次の**両方**を満たすときだけ。
A file may therefore be moved out of `_app.tsx` only if **both** hold:

- **(a) 持ち主が 1 つ** — ファイルが定義するすべての class / id が、1 つのページのコンポーネントツリー（または明示的に列挙した小さなページ集合）からしか到達できない。共有コンポーネントが使うファイルは、多くのページがそのコンポーネントを取り込むのでページ専用ではない。
- **(a) single owner** — every class/id it defines is reachable only from one page's component tree (or one small, explicitly enumerated set of pages). A file used by a shared component is not page-scoped, because many pages pull that component in.
- **(b) カスケードで引き分けが無い** — セレクタが、グローバルバンドルに残る同じ要素向けのセレクタとの import 順に依存しない。完全なセレクタ、同居する class、詳細度、重要度、プロパティの値を確かめること。class 名が共通というだけでは衝突ではない。互いに交わらないページやモーダルのスコープは同じ要素に当たらず、より強いセレクタや `!important` は順序に関係なく勝ち、宣言が同じなら結果も同じになる。順序に依存するルールはグローバルに残す。
- **(b) no tie in the cascade** — its selectors do not depend on import order against selectors that stay in the global bundle on the same element. Check the complete selector, coexisting classes, specificity, importance, and property values. A shared class name alone is not a collision: disjoint page/modal scopes cannot match the same element, a stronger selector or `!important` wins regardless of order, and equal declarations give the same result. Keep order-dependent rules global.

残すファイルにも順序は重要で、**`_app.tsx` に残る import の並びを入れ替えない**。いくつかは import 順で意図的に互いを上書きしている（下記を参照）。
Order matters for the files that stay, too: **do not reshuffle the remaining `_app.tsx` imports**. Several of them deliberately override each other by import order (see below).

## ページごとに読み込んでいるもの / Currently linked per page

ページまたはコンポーネントごとに、そのページが持つスタイルシートの一覧（`React-managed` は React が `precedence` 付きの link を管理する意味）。
| ページ / コンポーネント (Page / component) | ページ専用のスタイルシート (Page-owned stylesheets) |
| --- | --- |
| `components/memo/page/MemoPage.tsx` | `memo/static/css/memo_form.css`（React が管理、`precedence="memo"`）/ (React-managed, `precedence="memo"`) |
| `pages/lp.tsx` | `pages/lp/lp.css` |
| `pages/help.tsx`, `pages/privacy.tsx`, `pages/terms.tsx` | `pages/lp/lp.css`, `pages/docs/docs.css` |
| `pages/chat/lp.tsx` | `pages/lp/lp.css`, `pages/chat_lp/chat_lp.css` |
| `pages/memo/lp.tsx` | `pages/lp/lp.css`, `pages/memo_lp/memo_lp.css` |
| `pages/prompt_share/lp.tsx` | `pages/lp/lp.css`, `pages/prompt_share_lp/prompt_share_lp.css` |
| `components/prompt_share/prompt_category_page.tsx` | `pages/lp/lp.css`, `pages/prompt_share_category/prompt_share_category.css` |
| `pages/oauth/authorize.tsx` | `pages/oauth_authorize/oauth_authorize.css` |
| `pages/shared/memo/[token].tsx` | `pages/shared_memo.css` |
| `pages/shared/prompt/[id]/[[...slug]].tsx` | `pages/shared_prompt.css` |
| `pages/admin/index.tsx`, `pages/admin/login.tsx` | `pages/admin/admin.css`（React が管理、`precedence="admin"`）。ダッシュボードのデモコードのカードは `pages/admin/demo_codes.css`（`precedence="demo-codes"`）を足す / (React-managed, `precedence="admin"`); the dashboard's demo code card adds `pages/admin/demo_codes.css` (`precedence="demo-codes"`) |

`prompt_category_page.tsx` は、スタイルがページ本体ではなく共有コンポーネントに属する場合の形を示している。コンポーネントが自分の `next/head` の link を描画する。
`prompt_category_page.tsx` shows the shape to use when the styles belong to a shared component rather than a page shell: the component renders its own `next/head` link.

## `_app.tsx` に残すものと理由 / What stays in `_app.tsx`, and why

グローバルバンドルには、共有コンポーネントと、ページ単位の上書きの連鎖がまだ残っている。以下の各グループは条件 (a)、(b)、またはその両方を満たさない。誰も理由を調べ直さなくて済むよう、理由を記録しておく。
The global bundle still contains shared components and page override chains. Each group below fails test (a), test (b), or both — the reason is recorded so nobody has to re-derive it:

- `base/form_zoom_guard.css` — 本当に共有で、バンドル内で `font-size` に `!important` を付けてよい唯一のファイル。`@media (pointer: coarse)` で `input` / `textarea` / `select` を 16px 以上にし、iOS Safari がフォーカス時にページをズームしないようにする。デザイントークンは 16px 未満で、既存のコントロールは `(0,2,0)` 程度に強いクラスセレクタで装飾されているため、このガードは詳細度では勝てない。勝つのは import 順ではなく `!important` で、`_app.tsx` の最後に置くのは前提ではなく保険。16px より大きくしたいコントロールは、そのページのスタイルシートから書き戻し、`tests/form_zoom_guard_style.test.ts` が両者が等しいことを検証する。サンドボックス iframe は、グローバル CSS が `srcDoc` のドキュメントに届かないため、`components/chat_page/sandbox_artifact_frame.tsx` に自前のコピーを持つ。
- `base/form_zoom_guard.css` — genuinely shared, and the one file in the bundle allowed to mark `font-size` `!important`. It raises `input` / `textarea` / `select` to at least 16px under `@media (pointer: coarse)` so iOS Safari stops zooming the page on focus; the design tokens stay below 16px and existing controls are styled through class selectors as specific as `(0,2,0)`, so the guard cannot win on specificity. It wins through `!important`, not through import order, and being last in `_app.tsx` is insurance rather than a precondition. Controls deliberately larger than 16px are written back from their page stylesheet, and `tests/form_zoom_guard_style.test.ts` asserts the two stay equal. The sandbox iframe carries its own copy in `components/chat_page/sandbox_artifact_frame.tsx` because global CSS never reaches a `srcDoc` document.
- `styles/globals.css`、`base/*`、`components/*` — 本当に共有。`globals.css` は `_app` レベルのシェル（`GlobalAiAgent`、`NetworkStatusBanner`、エラーバウンダリ）のスタイルも持ち、これらは全ルートで描画される。
- `styles/globals.css`, `base/*`, `components/*` — genuinely shared. `globals.css` also styles the `_app`-level shell (`GlobalAiAgent`, `NetworkStatusBanner`, the error boundary), which renders on every route.
  - Chaco モーダルの高さは `--draggable-modal-viewport-height` に結び付いている。この変数は `components/ui/DraggableModal.tsx` が、計測した visual viewport（`hooks/use_visual_viewport_height.ts`）から書き込む。画面キーボードは visual viewport を縮めるが `100vh` は縮まないので、高さの上限と `min-height` の下限の両方をこの変数で抑える。px 固定の下限だと、縮んだ viewport をモーダルがはみ出し、入力欄がキーボードの裏に隠れる。`tests/ai_agent_style.test.ts` がこの結び付きを検証する。
  - The Chaco modal's height is bound to `--draggable-modal-viewport-height`, which `components/ui/DraggableModal.tsx` writes from the measured visual viewport (`hooks/use_visual_viewport_height.ts`). The on-screen keyboard shrinks that viewport while `100vh` does not, so both the height cap and the `min-height` floor are capped by it - a plain px floor would let the modal outgrow the shrunken viewport and hide its input behind the keyboard. `tests/ai_agent_style.test.ts` asserts the binding.
  - `components/modal_surface.css` が唯一のモーダルの外殻で、中央に出すモーダルはすべて `components/ui/modal_shell.tsx`（`ModalShell`、`<body>` へポータル）経由で、`cc-modal` のオーバーレイ class と `cc-modal__panel / __header / __body / __footer / __btn` の部品を使って描かれる。配色は `base/variables.css` の `--modal-*` トークンだけを使う。ページがアクセント色を変えるときは、オーバーレイに付けるスコープ class（例: `.prompt-share-modal`）上で `--modal-accent`、`--modal-accent-hover`、`--modal-accent-text`、`--modal-accent-soft`、`--modal-focus-ring` を上書きする。ページの CSS が整えるのはモーダルの中身だけで、2 つ目の外殻は作らない。`globals.css` は共有の共有モーダルの中身（`.cc-share-modal__*`）を同じトークンの上で持つ。
  - `components/modal_surface.css` is the one modal shell: every centered modal renders through `components/ui/modal_shell.tsx` (`ModalShell`, portaled to `<body>`) with the `cc-modal` overlay class and the `cc-modal__panel / __header / __body / __footer / __btn` parts. It paints only with the `--modal-*` tokens from `base/variables.css`; a page changes the accent by overriding `--modal-accent`, `--modal-accent-hover`, `--modal-accent-text`, `--modal-accent-soft` and `--modal-focus-ring` on a scope class it puts on the overlay (e.g. `.prompt-share-modal`). Page CSS styles only the modal's contents, never a second shell. `globals.css` keeps the shared share-modal contents (`.cc-share-modal__*`) on the same tokens.
- **`pages/chat/*` 系列**（`setup`、`skills`、`chat_layout`、`chat_messages`、`chat_markdown`、`chat_input`、`tasks_order/*`、`project`、`index`）— (b) を満たさない。これらのファイルは import 順で互いを上書きし、`:where(body.chat-page, .chat-page-shell)` のスコープを共有している。また `chat_messages` / `chat_markdown` / `chat_layout` / `index` は `/shared/[token]` でも必要。（以前は import 順で決まっていた 2 つのモーダルの競合 — `.skill-detail-modal__instructions` と `.task-detail-section-body`、`.project-overlay__close` と `.icon-button` — は、それらのモーダルが共有の `cc-modal` の面で描かれるようになって解消した。）
- **`pages/chat/*` family** (`setup`, `skills`, `chat_layout`, `chat_messages`, `chat_markdown`, `chat_input`, `tasks_order/*`, `project`, `index`) — fails (b). These files override each other by import order and share the `:where(body.chat-page, .chat-page-shell)` scope, and `chat_messages`/`chat_markdown`/`chat_layout`/`index` are also needed by `/shared/[token]`. (The two modal ties that used to be decided by import order — `.skill-detail-modal__instructions` vs `.task-detail-section-body`, `.project-overlay__close` vs `.icon-button` — are gone now that those modals render through the shared `cc-modal` surface.)
- **`pages/chat/shared_chat.css`** — (a) は満たす（`/shared/[token]` だけ）が (b) を満たさない。`.shared-chat-page` と `pages/chat/index.css` の `.chat-page-shell` はどちらも `(0,1,0)` で、同じ要素の `align-items` と `padding` を設定している。`shared_chat.css` が勝つのは、後から import されているからにすぎない。
- **`pages/chat/shared_chat.css`** — passes (a) (only `/shared/[token]`) but fails (b). `.shared-chat-page` and `pages/chat/index.css` `.chat-page-shell` are both `(0,1,0)` and both set `align-items` and `padding` on the same element; `shared_chat.css` wins only because it is imported later.
- **`pages/user_settings/user_settings.css`**（約 3,300 行）— (a)(b) の両方を満たさない。`edit-prompt-modal__*` と `prompt-card__*` の系列を定義していて、`/prompt_share` でも描画される。また 55 個の名前がバンドルの他の部分と重なる。
- **`pages/user_settings/user_settings.css`** (~3,300 lines) — fails both. It defines the `edit-prompt-modal__*` and `prompt-card__*` families, which `/prompt_share` renders too, and 55 of its names overlap the rest of the bundle.
- **`prompt_share/*` 系列**（`base`、`foundation`、`cards-actions`、`modals-composer`、`ai-agent`、`responsive`、`button-system`、`dark-mode`）— (a)(b) の両方を満たさない。7 つの `prompt_share.*` ファイルは意図した上書きの連鎖（foundation → cards-actions → modals-composer → ai-agent → responsive → button-system → dark-mode）で、`dark-mode` と `responsive` は定義するほぼすべての名前でバンドルの他の部分と重なる。`prompt-card*` / `edit-prompt-modal__*` / `search-box` は `/settings` と `/` とも共有している。
- **`prompt_share/*` family** (`base`, `foundation`, `cards-actions`, `modals-composer`, `ai-agent`, `responsive`, `button-system`, `dark-mode`) — fails both. The seven `prompt_share.*` files are an intentional override chain (foundation → cards-actions → modals-composer → ai-agent → responsive → button-system → dark-mode); `dark-mode` and `responsive` overlap the rest of the bundle on nearly every name they define, and `prompt-card*` / `edit-prompt-modal__*` / `search-box` are shared with `/settings` and `/`.

### メモ画面のスタイルシートの境界 / Memo stylesheet boundary

`memo/static/css/memo_form.css` は `/memo`（ポータルされるモーダルを含む）が持つ。`mini-chat-*` のルールは `.memo-modal .memo-modal__agent-panel` にスコープされ、`memo-code-block-*` のルールはメモ画面にスコープされる。グローバルのサポートエージェントやチャット画面のスタイルには触れない。メモのモーダルのセレクタは共有のモーダルの面より強い。モバイルのオーバーレイのルールは `.modal-base.memo-modal-scope` / `.modal-base.memo-compose-mobile-modal` を使い、直接読み込みでもクライアント遷移でも、全画面のシートが共有オーバーレイの padding に勝つ。グローバルのボタンの影・filter のリセットと、タッチ入力の font-size ガードは `!important` を使うので、メモの link がバンドルされたスタイルより前に来ても勝つ。メモ専用の `sr-only` の宣言はグローバルのユーティリティと一致している。メモのアニメーション定義と `--memo-spring` / `--memo-press` 変数はメモのスタイルシートからしか使われない。`miniChatTyping` は共有のサポートエージェントのために、グローバルに定義したまま残す。
`memo/static/css/memo_form.css` is owned by `/memo`, including its portaled modals. Its `mini-chat-*` rules are scoped to `.memo-modal .memo-modal__agent-panel`, and its `memo-code-block-*` rules to the memo page; they do not style the global support agent or chat pages. The memo modal's selectors outrank the shared modal surface. The mobile overlay rules use `.modal-base.memo-modal-scope` / `.modal-base.memo-compose-mobile-modal` so the full-screen sheet wins against the shared overlay padding on both direct loads and client navigation. The global button shadow/filter reset and touch input font-size guard use `!important`, so they still win when the memo link comes before the bundled styles. The memo-scoped `sr-only` declarations agree with the global utility. Memo animation definitions and `--memo-spring` / `--memo-press` variables are consumed only by the memo stylesheet; `miniChatTyping` remains globally defined for the shared support agent.

ルールを足すときは、これらのスコープとカスケードの境界を守る。ルート遷移では link がグローバルバンドルの後ろに置かれることがあり、直接読み込みでは前に置かれる。どちらでも同じ見た目になること。
Keep these scope and cascade boundaries when adding rules. A route change can place the link after the global bundle, while a direct load places it before; both must render identically.

メモの link は `next/head` ではなく React の `precedence` prop で直接描画する。そうすれば、クライアント遷移でスタイルシートの準備前にメモの画面が表示されることがない。バックグラウンドのルート準備はアセットの preload だけを行い、メニューの意図（hover など）では React の `preinit` で遷移前にスタイルシートを準備する。React はページを離れたあともこの link を保持することがあるので、そのルールはメモにスコープされたままにしておく。[React のスタイルシートのリファレンス](https://react.dev/reference/react-dom/components/link#special-behavior-for-stylesheets)を参照。
The memo link is rendered directly with React's `precedence` prop, rather than through `next/head`, so client navigation cannot display the memo shell before its stylesheet is ready. Background route preparation only preloads the asset; menu intent uses React's `preinit` to prepare the stylesheet before navigation. React can retain this link after leaving the page; its rules must remain memo-scoped. See the [React stylesheet reference](https://react.dev/reference/react-dom/components/link#special-behavior-for-stylesheets).

## 移動候補の確認方法 / Checking a candidate

ビルドが防護柵になる。グローバル CSS ファイルを `_app` の外から import すると、Next が `npm run build` を失敗させる。それ以外にも、`npm test` には CSS とコンポーネントのソース文字列を読んで検証する `*_style.test.ts` が約 18 ファイル含まれる。移動後にそのどれかが落ちたなら、見た目の契約が実際に変わったということなので、アサーションを直さず原因を調べる。
The build is the guard rail: Next fails `npm run build` if a global CSS file is imported outside `_app`. Beyond that, `npm test` includes roughly 18 `*_style.test.ts` files that read CSS and component source text and assert on it — if one fails after a move, a visual contract really did change; investigate instead of editing the assertion.
