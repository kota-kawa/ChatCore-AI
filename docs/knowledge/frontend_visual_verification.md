# フロントエンドの実描画確認（Playwright）

見た目や操作に影響するフロントエンド変更を PR にする前に、Playwright で実際に描画・操作して確認する手順です。単体テスト（jsdom）では `touch-action`、カスケードの後勝ち、`position: fixed` の包含ブロックなどが再現できないため、この確認に価値があります。対象外（描画に出ない変更）は `lint`／`typecheck`／テストで足ります。

## 合格条件
- スクリーンショットの見た目だけで完了と判断しない。`getComputedStyle` と `getBoundingClientRect` で、意図した値になっているかを数値で確認する。過去に同詳細度のルールへカスケードで負けて `position` が変わっておらず、スクショが「それっぽく」見えたため見落とした事例がある。
- Playwright で取得したスクリーンショットを実際に目視し、レイアウト崩れ、文字切れ、重なり、余白、テーマ間の差異がないことを確認する。スクリーンショットの PR 添付は必須ではないが、確認結果は PR 本文に記録する。
- before／after を比較するときは、スクショのハッシュ比較まで行い「実は無変化」を検出する。
- PC 幅とスマホ幅（例: 390×740）の両方、`data-theme` のライトとダークの両方を確認する。
- タッチ操作に関わる変更は `hasTouch: true, isMobile: true` のコンテキストで確認する。長押し→移動のような時間依存のジェスチャーは `page.touchscreen` では再現できないので、CDP の `Input.dispatchTouchEvent` を使う。
- 確認した画面・ビューポート・テーマ・実測値を PR 本文に書く。添付するスクリーンショットは `assets/images/` にコミットする。

## 起動
- `frontend/` で `npm run dev` を起動する。本番ビルドはハイドレーション不一致を `Minified React error #418` としか出さないため、原因特定は dev で行う。
- バックエンドが必要な画面は `python3 app.py` を起動するか、`page.route` で対象 API をモックする。状態を変更する操作を試すときは `**/api/csrf-token`（`{"csrf_token": "..."}` を返す）のモックも必要で、忘れると `Failed to fetch CSRF token` のエラーになる。
- SSR がデータに依存するページ（`/prompt_share`、`/shared/*`）は、`BACKEND_URL` の既定値 `http://localhost:5004` にモック API を立てないと SSR が空になり、不一致が再現しない。
- ログインが要る画面は、`frontend/pages/__ui_probe.tsx` のような一時ページに実コンポーネントを載せて描画するのが速い。メモ詳細は `frontend/tests/memo_page_context_harness.tsx` のスタブでそのまま描画できる。一時ページは検証後に必ず削除し、PR に含めない。

## ツール
- Claude Code では Playwright MCP（`browser_navigate`／`browser_resize`／`browser_snapshot`／`browser_take_screenshot`／`browser_evaluate`）を使う。出力先の `.playwright-mcp/` はセッションの一時ファイルで、git 管理外。
- MCP が無い環境（Codex など）では Node スクリプトから Playwright を使う。`playwright` は package.json に追加せず、`npx playwright@<固定版>` か別ツリーの `node_modules` を借用する。ブラウザ実体は `~/.cache/ms-playwright/chromium_headless_shell-<revision>/chrome-headless-shell-linux64/chrome-headless-shell` を `executablePath` に指定し、`args: ["--no-sandbox", "--disable-gpu"]` を付ける。revision は借用した Playwright の `browsers.json` に合わせる。

## 既知の落とし穴
- `next dev` の開発オーバーレイ `<nextjs-portal>` が全画面でポインタを奪い、`page.click` がタイムアウトする。`page.$eval(selector, el => el.click())` で回避する（`remove()` しても再挿入される）。
- グローバル CSS（`frontend/pages/_app.tsx` 経由）を編集したら `next dev` を再起動する。Turbopack が古いバンドルを配り続けることがあるので、`curl` で `/_next/static/chunks/[root-of-the-server]__*.css` を取得し、新しい宣言が載っているかを確認する。
- ハイドレーション不一致はブラウザのタイムゾーン（`timezoneId`）と表示言語（cookie `chatcore_locale`）で条件が変わる。詳しくは `debugging.md` を参照。
- iOS のキーボード表示は `visualViewport.height` を縮めて `resize` を dispatch、Android は `page.setViewportSize` で縮めて再現する。
