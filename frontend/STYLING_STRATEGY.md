# Styling Strategy

- Primary styling axis: **CSS custom properties + modular CSS files**.
- `:root` tokens are defined only in `public/static/css/base/variables.css`.
- Page-level visual differences (for example scrollbars) use page-scoped variables such as `--page-scrollbar-*`, not duplicated `:root` tokens.
- Bootstrap is loaded once in `pages/_document.tsx` (CSS, Icons, JS bundle).
- Tailwind utility usage remains in admin pages as a legacy exception; new shared tokens must still be defined via `variables.css`.
