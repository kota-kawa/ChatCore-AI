# Frontend feature map

Frontend は Next.js Pages Router を使います。ページは画面の入口、`components/` は表示、`hooks/` と `contexts/` は画面状態、`lib/` と `scripts/` は API・ストリーム・ブラウザ共通処理を担当します。

## 共通の実行経路

```text
frontend/pages/<page>.tsx
        ↓
components/ + hooks/ + contexts/
        ↓
lib/<feature>/ または scripts/core/resilient_fetch.ts
        ↓
FastAPI endpoint（Cookie / CSRF / JSON または SSE）
```

`frontend/pages/_app.tsx` は全ページの CSS、翻訳、SWR、テーマ、ネットワーク状態、グローバルエラー境界を初期化します。認証ページ以外には `GlobalAiAgent` も配置されます。

## ページと機能の対応

| URL | ページ入口 | 主な UI／状態 | 主な Backend 境界 |
| --- | --- | --- | --- |
| `/` | `pages/index.tsx` | `components/chat_page/`、`HomePageContextProvider`、`hooks/chat_page/`、`SkillSection` | `/api/chat`、チャット部屋・タスク・個人Skill・プロジェクト API、SSE |
| `/login`, `/register`, `/oauth/authorize` | `pages/login.tsx`, `register.tsx`, `oauth/authorize.tsx` | `components/auth/auth_gateway_page.tsx` と `auth_gateway_modules/` | `/api/current_user`、メール認証、Google OAuth、Passkey |
| `/settings` | `pages/settings.tsx` | `components/settings/` | `/api/user/*`、`/api/passkeys`、`/prompt_manage/api/*`、`/prompt_share/api/like` |
| `/memo` | `pages/memo.tsx` → `components/memo/page/MemoPage.tsx` | `components/memo/`、`MemoPageContextProvider`、`hooks/memo_page/`、`lib/memo/` | `/memo/api/*`、`/api/context-facts/*` |
| `/prompt_share` | `pages/prompt_share/index.tsx` | `components/prompt_share/`、プロンプト共有 hook 群 | `/prompt_share/api/*`、`/search/prompts`、`/api/*` |
| `/prompt_share/manage_prompts` | `pages/prompt_share/manage_prompts.tsx` | 設定用 prompt component、`resilientFetch` | `/prompt_manage/api/*` |
| `/shared/[token]` | `pages/shared/[token].tsx` | `components/shared_chat/` | 共有チャット取得・fork API |
| `/shared/memo/[token]` | `pages/shared/memo/[token].tsx` | 共有メモ表示 | `/memo/api/shared` |
| `/shared/prompt/[id]/[[...slug]]` | `pages/shared/prompt/[id]/[[...slug]].tsx` | 共有プロンプト詳細 | `/prompt_share/api/prompts/{id}` |
| `/admin`, `/admin/login` | `pages/admin/index.tsx`, `login.tsx` | 管理画面固有の UI と Tailwind 互換スタイル | `/admin/api/*` |
| `/lp`, `/chat/lp`, `/memo/lp`, `/prompt_share/lp` | 各 `pages/*/lp.tsx` | LP 専用 components と page CSS | 原則公開ページ。必要なデータ取得のみ API を利用 |
| `/help`, `/terms`, `/privacy` | 各ページ入口 | `components/docs/`、help コンテンツ | 静的／翻訳データ中心 |

`pages/api/healthz.ts`、`robots.txt.tsx`、`sitemap.xml.tsx` はアプリ画面ではなく Next.js の運用・検索エンジン向けエントリーポイントです。

## 共有ランタイムと API 層

- `scripts/core/resilient_fetch.ts`: timeout、再試行、ネットワーク切り替え時のリクエストを吸収する一般 fetch 境界です。
- `lib/data/swr_fetcher.ts`: GET の JSON 取得、HTTP エラー正規化、SWR 既定値をまとめます。
- `scripts/core/csrf.ts`: `/api/csrf-token` を使って状態変更リクエストへ CSRF ヘッダーを付けます。
- `lib/chat_page/api_contract.ts`: チャット履歴・生成 UI パーツ・検索画像などの実行時正規化を担当します。
- `types/generated/api_schemas.ts`: Backend Pydantic model から生成される契約です。直接編集しません。
- `contexts/locale_context.tsx` と `lib/i18n/`: 日本語／英語の表示状態・翻訳カタログを管理します。
- `components/ui/copy_button.tsx`（`CopyButton`）＋ `hooks/use_copy_feedback.ts` ＋ `lib/copy_feedback.ts`: 全画面共通のコピーボタン。アイコンのみで、押すと数秒チェックマークに変わります。新しいコピー操作はこれを使い、個別実装を増やしません。

共有モーダルのSNS URL生成、Web Share API、クリップボード操作、共有本文の表示は共通ランタイム／UI部品で処理します。チャット、メモ、プロンプト固有のURL発行とステータス文言は各adapterに残します。共有Chatのforkと公開PromptのTask／Skill取り込みは、共通の操作状態・二重実行防止・ボタン外観を使いながら、APIと遷移は機能ごとの契約を維持します。

## 変更時の境界

ページの UI だけなら対応する `pages/` と `components/`、画面状態なら `hooks/`／`contexts/`、API の取得・再試行なら `lib/`／`scripts/`を優先します。JSON の形状を変える場合は Backend model と生成スキーマも更新し、SSE の形状を変える場合は `lib/chat_page/` の parser と対象テストを同時に確認します。
