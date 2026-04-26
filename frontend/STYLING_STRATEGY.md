# Styling Strategy

- Primary styling axis: **CSS custom properties + modular CSS files**.
- `:root` tokens are defined only in `public/static/css/base/variables.css`.
- Page-level visual differences (for example scrollbars) use page-scoped variables such as `--page-scrollbar-*`, not duplicated `:root` tokens.
- Page CSS should be linked from the owning page with static CSS under `public/`, instead of importing large page entry CSS files into `_app`.
- Bootstrap's full CSS bundle is not loaded. `bootstrap-icons` remains available via npm, and the few legacy Bootstrap class names still used by prompt/settings screens are covered by `styles/bootstrap-compat.css`.
- Tailwind utility usage remains in admin pages as a legacy exception; new shared tokens must still be defined via `variables.css`.
