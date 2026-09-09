# Styling Strategy

- Primary styling axis: **CSS custom properties + modular CSS files**.
- `:root` tokens are defined only in `public/static/css/base/variables.css`.
- Page-level visual differences (for example scrollbars) use page-scoped variables such as `--page-scrollbar-*`, not duplicated `:root` tokens.
- Bootstrap's full CSS bundle is not loaded. `bootstrap-icons` remains available via npm, and the few legacy Bootstrap class names still used by prompt/settings screens are covered by `styles/bootstrap-compat.css`.
- Tailwind utility usage remains in admin pages as a legacy exception; new shared tokens must still be defined via `variables.css`.

## Where a stylesheet is loaded

There are exactly two places CSS enters the app:

1. **The global bundle** — `import "...css"` statements at the top of `pages/_app.tsx`. Webpack concatenates them in import order and Next emits them as one `<link>` set on every route.
2. **A page `<link>`** — `<link rel="stylesheet" href="/static/css/..." />` inside the owning page's `next/head` (in this repo, as a child of `<SeoHead>`). Files under `frontend/public/` are served at the matching URL path, so `public/static/css/pages/docs/docs.css` is `/static/css/pages/docs/docs.css`.

New page-only CSS should use form 2. Nothing new should be added to `_app.tsx` unless it is genuinely shared.

### Cascade rule you must respect before moving a file out of `_app`

`next/document`'s `<Head>` renders the page's own `next/head` children **before** the bundled `_app` CSS links (`Head.render()` emits `head` and then `getCssLinks(files)`). So moving a file out of `_app` moves it **earlier** in the cascade, not later: after the move, every rule still in the global bundle wins any tie against it. On client-side navigation the injected `<link>` lands at the end of `<head>` instead, so the position is not even stable.

A file may therefore be moved out of `_app.tsx` only if **both** hold:

- **(a) single owner** — every class/id it defines is reachable only from one page's component tree (or one small, explicitly enumerated set of pages). A file used by a shared component is not page-scoped, because many pages pull that component in.
- **(b) no tie in the cascade** — its selectors do not collide with selectors that stay in the global bundle at the same specificity on the same element. In practice this means: its key (rightmost) class/id names appear in no other stylesheet, and no element that carries one of its classes also carries a class styled for the same property by the remaining bundle.

Order matters for the files that stay, too: **do not reshuffle the remaining `_app.tsx` imports**. Several of them deliberately override each other by import order (see below).

## Currently linked per page

| Page / component | Stylesheets linked from `next/head` |
| --- | --- |
| `pages/lp.tsx` | `pages/lp/lp.css` |
| `pages/help.tsx`, `pages/privacy.tsx`, `pages/terms.tsx` | `pages/lp/lp.css`, `pages/docs/docs.css` |
| `pages/chat/lp.tsx` | `pages/lp/lp.css`, `pages/chat_lp/chat_lp.css` |
| `pages/memo/lp.tsx` | `pages/lp/lp.css`, `pages/memo_lp/memo_lp.css` |
| `pages/prompt_share/lp.tsx` | `pages/lp/lp.css`, `pages/prompt_share_lp/prompt_share_lp.css` |
| `components/prompt_share/prompt_category_page.tsx` | `pages/lp/lp.css`, `pages/prompt_share_category/prompt_share_category.css` |
| `pages/oauth/authorize.tsx` | `pages/oauth_authorize/oauth_authorize.css` |
| `pages/shared/memo/[token].tsx` | `pages/shared_memo.css` |
| `pages/shared/prompt/[id]/[[...slug]].tsx` | `pages/shared_prompt.css` |

`prompt_category_page.tsx` shows the shape to use when the styles belong to a shared component rather than a page shell: the component renders its own `next/head` link.

## What stays in `_app.tsx`, and why

The global bundle is still large (~37k lines). Each group below fails test (a), test (b), or both — the reason is recorded so nobody has to re-derive it:

- `styles/globals.css`, `styles/bootstrap-compat.css`, `base/*`, `components/*` — genuinely shared. `globals.css` also styles the `_app`-level shell (`GlobalAiAgent`, `NetworkStatusBanner`, the error boundary), which renders on every route.
  - `components/modal_surface.css` is the one modal shell: every centered modal renders through `components/ui/modal_shell.tsx` (`ModalShell`, portaled to `<body>`) with the `cc-modal` overlay class and the `cc-modal__panel / __header / __body / __footer / __btn` parts. It paints only with the `--modal-*` tokens from `base/variables.css`; a page changes the accent by overriding `--modal-accent`, `--modal-accent-hover`, `--modal-accent-text`, `--modal-accent-soft` and `--modal-focus-ring` on a scope class it puts on the overlay (e.g. `.prompt-share-modal`). Page CSS styles only the modal's contents, never a second shell. `globals.css` keeps the shared share-modal contents (`.cc-share-modal__*`) on the same tokens.
- **`pages/chat/*` family** (`setup`, `skills`, `chat_layout`, `chat_messages`, `chat_markdown`, `chat_input`, `tasks_order/*`, `project`, `index`) — fails (b). These files override each other by import order and share the `:where(body.chat-page, .chat-page-shell)` scope, and `chat_messages`/`chat_markdown`/`chat_layout`/`index` are also needed by `/shared/[token]`. Concrete ties that would flip if any one file moved: `.skill-detail-modal__instructions` vs `setup.css` `.task-detail-section-body` (`max-height`) and `.project-overlay__close` vs `base/buttons.css` `.icon-button` (`background`/`border`/`color`) — same element, same specificity, decided purely by import order today.
- **`pages/chat/shared_chat.css`** — passes (a) (only `/shared/[token]`) but fails (b). `.shared-chat-page` and `pages/chat/index.css` `.chat-page-shell` are both `(0,1,0)` and both set `align-items` and `padding` on the same element; `shared_chat.css` wins only because it is imported later.
- **`memo/memo_form.css`** (8,544 lines) — fails both. It defines the whole `mini-chat-*` family, which the `GlobalAiAgent` shell and `/prompt_share` also use, plus `memo-code-block-*` used on `/` and `/shared/[token]`, plus `primary-button`, `secondary-button`, `sr-only` and the `is-*` state classes; 64 of its names are also defined by other files in the bundle.
- **`pages/user_settings/user_settings.css`** (~3,300 lines) — fails both. It defines the `edit-prompt-modal__*` and `prompt-card__*` families, which `/prompt_share` and `/prompt_share/manage_prompts` render too, and 55 of its names overlap the rest of the bundle.
- **`prompt_share/*` family** (`base`, `foundation`, `cards-actions`, `modals-composer`, `ai-agent`, `responsive`, `button-system`, `dark-mode`, `prompt_manage`) — fails both. The seven `prompt_share.*` files are an intentional override chain (foundation → cards-actions → modals-composer → ai-agent → responsive → button-system → dark-mode); `dark-mode` and `responsive` overlap the rest of the bundle on nearly every name they define, and `prompt-card*` / `edit-prompt-modal__*` / `search-box` are shared with `/settings`, `/prompt_share/manage_prompts` and `/`.

## Checking a candidate

The build is the guard rail: Next fails `npm run build` if a global CSS file is imported outside `_app`. Beyond that, `npm test` includes roughly 18 `*_style.test.ts` files that read CSS and component source text and assert on it — if one fails after a move, a visual contract really did change; investigate instead of editing the assertion.
