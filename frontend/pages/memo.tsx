// メモページ（/memo）。画面本体は MemoPage コンポーネントで、クローラー向けの要約 MemoCrawlSummary もこのページから再公開する。
// The memo page (/memo). The screen itself is the MemoPage component; this page also re-exports MemoCrawlSummary, the summary for crawlers.

import MemoPage from "../components/memo/page/MemoPage";
export { MemoCrawlSummary } from "../components/memo/MemoCrawlSummary";

export default MemoPage;
