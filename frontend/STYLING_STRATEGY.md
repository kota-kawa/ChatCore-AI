# スタイルの方針 / Styling Strategy

CSSカスタムプロパティと分割CSSを基本とします。rootトークンはvariables.cssだけに定義し、値を変えたらDESIGN_TOKENS.mdも同じコミットで更新します。スクロールバーなどの画面差はページ固有変数にします。Bootstrap CSSは使わずアイコンだけを残します。Tailwindの残存利用とpreflightは全画面の基礎表示へ影響するため、削除は独立した変更とし、新しいutilityは追加しません。

- Primary styling axis: **CSS custom properties + modular CSS files**.
- `:root` tokens are defined only in `public/static/css/base/variables.css`.
- The colour, radius and shadow tokens, and the rules for choosing them, are documented in `DESIGN_TOKENS.md` (Japanese). Change a value in `variables.css` and that document in the same commit.
- Page-level visual differences (for example scrollbars) use page-scoped variables such as `--page-scrollbar-*`, not duplicated `:root` tokens.
- Bootstrap's CSS is not loaded. Only `bootstrap-icons` remains, via npm.
- The admin pages no longer use Tailwind utility classes; the last user is `components/settings/prompt_category_select.tsx` (`min-w-0`, `flex-1`, `truncate`). `styles/globals.css` still imports Tailwind, which also brings its base reset (preflight) to every page, so removing the dependency changes base styles app-wide and needs its own change. Do not add new Tailwind utilities.

## スタイルの読み込み元 / Where a stylesheet is loaded

CSSの入口は次の2つです。共通バンドルは_app.tsxのimport順で連結され全ページに配信されます。ページ専用CSSは所有する画面からlinkで読み込み、クライアント遷移で表示準備を待つにはReactのprecedenceを使えます。public配下のファイルは対応するURLで配信します。

There are exactly two places CSS enters the app:

1. **The global bundle** — `import "...css"` statements at the top of `pages/_app.tsx`. Webpack concatenates them in import order and Next emits them as one `<link>` set on every route.
2. **A page `<link>`** — the owning page renders its stylesheet link. Existing pages use `next/head` (as a child of `<SeoHead>`). A page entered through client navigation can render `<link rel="stylesheet" href="..." precedence="..." />` directly so React manages the stylesheet and waits for it before displaying the page. Files under `frontend/public/` are served at the matching URL path, so `public/static/css/pages/docs/docs.css` is `/static/css/pages/docs/docs.css`.

新しいページ専用CSSには2番目の方法を使います。複数画面で共有しないものを_app.tsxへ追加しません。

New page-only CSS should use form 2. Nothing new should be added to `_app.tsx` unless it is genuinely shared.

### 読み込み元を移す前のカスケード確認 / Cascade rule you must respect before moving a file out of `_app`

直接読み込みでは、ページのnext/headは_appの共通CSSより前に出ます。そのため_appから外すとカスケード上は早くなり、同じ詳細度なら残った共通CSSが勝ちます。一方、クライアント遷移ではlinkがhead末尾へ入るため、順番も安定しません。

`next/document`'s `<Head>` renders the page's own `next/head` children **before** the bundled `_app` CSS links (`Head.render()` emits `head` and then `getCssLinks(files)`). So moving a file out of `_app` moves it **earlier** in the cascade, not later: after the move, every rule still in the global bundle wins any tie against it. On client-side navigation the injected `<link>` lands at the end of `<head>` instead, so the position is not even stable.

_appから移せるのは、(a)所有ページが限定され、(b)共通CSSと読み込み順に依存する競合がない場合だけです。共有コンポーネント用のCSSはページ専用とは扱いません。競合判定ではセレクター全体・同居クラス・詳細度・important・値を確認します。ページやモーダルのスコープが互いに排他的、優先順位が固定、または値が同じなら、名前の重複だけでは競合としません。

A file may therefore be moved out of `_app.tsx` only if **both** hold:

- **(a) single owner** — every class/id it defines is reachable only from one page's component tree (or one small, explicitly enumerated set of pages). A file used by a shared component is not page-scoped, because many pages pull that component in.
- **(b) no tie in the cascade** — its selectors do not depend on import order against selectors that stay in the global bundle on the same element. Check the complete selector, coexisting classes, specificity, importance, and property values. A shared class name alone is not a collision: disjoint page/modal scopes cannot match the same element, a stronger selector or `!important` wins regardless of order, and equal declarations give the same result. Keep order-dependent rules global.

残すimportも並べ替えません。意図して後勝ちにしている規則があります。

Order matters for the files that stay, too: **do not reshuffle the remaining `_app.tsx` imports**. Several of them deliberately override each other by import order (see below).

## ページごとの読み込み / Currently linked per page

以下は各ページまたは所有コンポーネントが読み込むスタイルの対応表です。

| Page / component | Page-owned stylesheets |
| --- | --- |
| `components/memo/page/MemoPage.tsx` | `memo/static/css/memo_form.css` (React-managed, `precedence="memo"`) |
| `pages/lp.tsx` | `pages/lp/lp.css` |
| `pages/help.tsx`, `pages/privacy.tsx`, `pages/terms.tsx` | `pages/lp/lp.css`, `pages/docs/docs.css` |
| `pages/chat/lp.tsx` | `pages/lp/lp.css`, `pages/chat_lp/chat_lp.css` |
| `pages/memo/lp.tsx` | `pages/lp/lp.css`, `pages/memo_lp/memo_lp.css` |
| `pages/prompt_share/lp.tsx` | `pages/lp/lp.css`, `pages/prompt_share_lp/prompt_share_lp.css` |
| `components/prompt_share/prompt_category_page.tsx` | `pages/lp/lp.css`, `pages/prompt_share_category/prompt_share_category.css` |
| `pages/oauth/authorize.tsx` | `pages/oauth_authorize/oauth_authorize.css` |
| `pages/shared/memo/[token].tsx` | `pages/shared_memo.css` |
| `pages/shared/prompt/[id]/[[...slug]].tsx` | `pages/shared_prompt.css` |
| `pages/admin/index.tsx`, `pages/admin/login.tsx` | `pages/admin/admin.css` (React-managed, `precedence="admin"`); the dashboard's demo code card adds `pages/admin/demo_codes.css` (`precedence="demo-codes"`) |

共通コンポーネントが所有するスタイルの例はprompt_category_page.tsxです。ページ枠ではなくコンポーネント自身がnext/headのlinkを描画します。

`prompt_category_page.tsx` shows the shape to use when the styles belong to a shared component rather than a page shell: the component renders its own `next/head` link.

## 共通読み込みに残す理由 / What stays in `_app.tsx`, and why

共通バンドルに残るのは共有部品とページ間の上書き連鎖です。以下は所有者限定または読み込み順の条件を満たさない理由です。

The global bundle still contains shared components and page override chains. Each group below fails test (a), test (b), or both — the reason is recorded so nobody has to re-derive it:

入力拡大防止CSSは全画面で共有します。粗いポインターの端末で入力文字を16px以上にし、iOS Safariの拡大を防ぎます。既存のクラス詳細度に勝つためfont-sizeにimportantを許す唯一のファイルであり、末尾配置自体は必須ではありません。16pxより大きい入力はページCSSで戻し、テストで値の一致を検査します。srcDocには共通CSSが届かないため、sandbox iframeにも同じ規則を持たせます。

- `base/form_zoom_guard.css` — genuinely shared, and the one file in the bundle allowed to mark `font-size` `!important`. It raises `input` / `textarea` / `select` to at least 16px under `@media (pointer: coarse)` so iOS Safari stops zooming the page on focus; the design tokens stay below 16px and existing controls are styled through class selectors as specific as `(0,2,0)`, so the guard cannot win on specificity. It wins through `!important`, not through import order, and being last in `_app.tsx` is insurance rather than a precondition. Controls deliberately larger than 16px are written back from their page stylesheet, and `tests/form_zoom_guard_style.test.ts` asserts the two stay equal. The sandbox iframe carries its own copy in `components/chat_page/sandbox_artifact_frame.tsx` because global CSS never reaches a `srcDoc` document.
globals.css・base・componentsは共通です。エージェント、ネットワーク通知、エラー境界も全ルートに出ます。エージェントの高さ上限と最小高さは実測したvisual viewportの変数に結び付け、画面キーボードで隠れないようにします。中央モーダルはbodyにportalするModalShellとcc-modalの共通枠へ統一し、modalトークンで描画します。ページ側はoverlayのスコープでアクセントだけを変え、内容のCSSを担当します。

- `styles/globals.css`, `base/*`, `components/*` — genuinely shared. `globals.css` also styles the `_app`-level shell (`GlobalAiAgent`, `NetworkStatusBanner`, the error boundary), which renders on every route.
  - The Chaco modal's height is bound to `--draggable-modal-viewport-height`, which `components/ui/DraggableModal.tsx` writes from the measured visual viewport (`hooks/use_visual_viewport_height.ts`). The on-screen keyboard shrinks that viewport while `100vh` does not, so both the height cap and the `min-height` floor are capped by it - a plain px floor would let the modal outgrow the shrunken viewport and hide its input behind the keyboard. `tests/ai_agent_style.test.ts` asserts the binding.
  - `components/modal_surface.css` is the one modal shell: every centered modal renders through `components/ui/modal_shell.tsx` (`ModalShell`, portaled to `<body>`) with the `cc-modal` overlay class and the `cc-modal__panel / __header / __body / __footer / __btn` parts. It paints only with the `--modal-*` tokens from `base/variables.css`; a page changes the accent by overriding `--modal-accent`, `--modal-accent-hover`, `--modal-accent-text`, `--modal-accent-soft` and `--modal-focus-ring` on a scope class it puts on the overlay (e.g. `.prompt-share-modal`). Page CSS styles only the modal's contents, never a second shell. `globals.css` keeps the shared share-modal contents (`.cc-share-modal__*`) on the same tokens.
チャットのCSS群は互いに読み込み順で上書きし、chat-pageスコープを共有するため移せません。一部は共有会話でも必要です。以前のモーダル間の競合は共通cc-modal化で解消しています。

- **`pages/chat/*` family** (`setup`, `skills`, `chat_layout`, `chat_messages`, `chat_markdown`, `chat_input`, `tasks_order/*`, `project`, `index`) — fails (b). These files override each other by import order and share the `:where(body.chat-page, .chat-page-shell)` scope, and `chat_messages`/`chat_markdown`/`chat_layout`/`index` are also needed by `/shared/[token]`. (The two modal ties that used to be decided by import order — `.skill-detail-modal__instructions` vs `.task-detail-section-body`, `.project-overlay__close` vs `.icon-button` — are gone now that those modals render through the shared `cc-modal` surface.)
共有会話CSSは単独ページ所有ですが、同じ詳細度で通常チャットのalign-itemsとpaddingを上書きするため、後から読む順番が必要です。

- **`pages/chat/shared_chat.css`** — passes (a) (only `/shared/[token]`) but fails (b). `.shared-chat-page` and `pages/chat/index.css` `.chat-page-shell` are both `(0,1,0)` and both set `align-items` and `padding` on the same element; `shared_chat.css` wins only because it is imported later.
設定CSSは編集モーダルと投稿カードのクラスを公開投稿画面でも使い、多数の名前が共通バンドルと重なるため、所有者とカスケードの両条件を満たしません。

- **`pages/user_settings/user_settings.css`** (~3,300 lines) — fails both. It defines the `edit-prompt-modal__*` and `prompt-card__*` families, which `/prompt_share` renders too, and 55 of its names overlap the rest of the bundle.
公開投稿CSSはfoundationからdark-modeまで意図的な上書き連鎖を持ちます。responsiveとdark-modeは他の共通規則と重なり、カード・編集モーダル・検索欄は設定画面やトップでも共有します。

- **`prompt_share/*` family** (`base`, `foundation`, `cards-actions`, `modals-composer`, `ai-agent`, `responsive`, `button-system`, `dark-mode`) — fails both. The seven `prompt_share.*` files are an intentional override chain (foundation → cards-actions → modals-composer → ai-agent → responsive → button-system → dark-mode); `dark-mode` and `responsive` overlap the rest of the bundle on nearly every name they define, and `prompt-card*` / `edit-prompt-modal__*` / `search-box` are shared with `/settings` and `/`.

### メモ画面のスタイル境界 / Memo stylesheet boundary

メモCSSはportal先モーダルを含め/memoが所有します。mini-chatとコード表示はメモ内へ限定し、共通エージェントやチャットには適用しません。モーダルのスコープと詳細度で共通枠より優先し、モバイルの全面シートでも共通overlayの余白に勝つようにします。importantの共通ボタンリセットと入力文字サイズは順番に関係なく有効です。sr-onlyの値も共通規則と揃えます。メモ専用のアニメーションと変数は専用CSS内で使い、共有のminiChatTypingだけは共通に残します。

`memo/static/css/memo_form.css` is owned by `/memo`, including its portaled modals. Its `mini-chat-*` rules are scoped to `.memo-modal .memo-modal__agent-panel`, and its `memo-code-block-*` rules to the memo page; they do not style the global support agent or chat pages. The memo modal's selectors outrank the shared modal surface. The mobile overlay rules use `.modal-base.memo-modal-scope` / `.modal-base.memo-compose-mobile-modal` so the full-screen sheet wins against the shared overlay padding on both direct loads and client navigation. The global button shadow/filter reset and touch input font-size guard use `!important`, so they still win when the memo link comes before the bundled styles. The memo-scoped `sr-only` declarations agree with the global utility. Memo animation definitions and `--memo-spring` / `--memo-press` variables are consumed only by the memo stylesheet; `miniChatTyping` remains globally defined for the shared support agent.

規則追加時もスコープとカスケードの境界を保ちます。直接読み込みとクライアント遷移でlinkの前後が逆でも、同じ見た目になる必要があります。

Keep these scope and cascade boundaries when adding rules. A route change can place the link after the global bundle, while a direct load places it before; both must render identically.

メモのlinkはnext/headではなくReactのprecedenceで管理し、CSSが準備できる前の画面表示を防ぎます。バックグラウンド準備はpreloadだけを行い、メニュー操作の意図が分かった時点でpreinitします。遷移後もlinkは残り得るため、規則はメモのスコープへ限定します。

The memo link is rendered directly with React's `precedence` prop, rather than through `next/head`, so client navigation cannot display the memo shell before its stylesheet is ready. Background route preparation only preloads the asset; menu intent uses React's `preinit` to prepare the stylesheet before navigation. React can retain this link after leaving the page; its rules must remain memo-scoped. See the [React stylesheet reference](https://react.dev/reference/react-dom/components/link#special-behavior-for-stylesheets).

## 移動候補の検証 / Checking a candidate

_app以外からglobal CSSをimportするとNextのbuildが失敗します。さらにstyle系テストがCSSとコンポーネントのソースを読み、表示契約を検査します。移動後の失敗はアサーションを変えて済ませず、実際に何の契約が変わったか調べます。

The build is the guard rail: Next fails `npm run build` if a global CSS file is imported outside `_app`. Beyond that, `npm test` includes roughly 18 `*_style.test.ts` files that read CSS and component source text and assert on it — if one fails after a move, a visual contract really did change; investigate instead of editing the assertion.
