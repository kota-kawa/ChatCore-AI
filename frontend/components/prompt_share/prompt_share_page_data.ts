import type { GetServerSideProps } from "next";

import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { normalizePromptData } from "../../scripts/prompt_share/formatters";
import type {
  PromptData,
  PromptFeedResponse,
  PromptPagination
} from "../../scripts/prompt_share/types";
import { localizedAbsoluteUrl } from "../../lib/seo";
import type { Locale } from "../../lib/i18n/config";
import { promptShareText } from "../../scripts/prompt_share/i18n";

export type PromptSharePageProps = {
  initialPrompts?: PromptData[];
  initialPagination?: PromptPagination | null;
};

// SEO向けのページ説明文。検索エンジンのスニペットとして表示される
// Page description for SEO; displayed as the search engine snippet
export const promptShareDescription =
  "Chat Coreのプロンプト共有ページです。文章作成・調査・画像生成に使えるAIプロンプト、再利用できるSKILL（スキル）、AI画像生成で作成した画像を探して、保存・共有できます。";

// 構造化データ（JSON-LD）。Googleがリッチリザルトとしてページを解釈できるようにする
// Structured data (JSON-LD) that helps Google understand and display this page as a rich result
export function getPromptShareStructuredData(locale: Locale) {
  return {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: promptShareText("promptShare.structuredName", undefined, locale),
    url: localizedAbsoluteUrl("/prompt_share", locale),
    description: promptShareText("promptShare.seoDescription", undefined, locale),
    inLanguage: locale,
    isPartOf: {
      "@type": "WebSite",
      name: "Chat Core",
      url: localizedAbsoluteUrl("/", locale)
    }
  };
}

export const promptShareStructuredData = getPromptShareStructuredData("ja");

// SSRで事前取得するプロンプトの最大件数。初期表示の速度とデータ量のバランスをとるための定数
// Maximum number of prompts fetched during SSR; balances initial render speed against payload size
const INITIAL_PROMPT_LIMIT = 24;

// バックエンドのオリジンを環境変数から取得し、末尾スラッシュを除去する
// Reads the backend origin from the environment variable and strips any trailing slashes
function getBackendOrigin() {
  return (process.env.BACKEND_URL || "http://localhost:5004").replace(/\/+$/, "");
}

// SSR時にプロンプト一覧を事前取得する。失敗した場合でも空配列でページを返し、CSRで再取得させる
// Pre-fetches the prompt list at SSR time; returns an empty array on failure so the client can retry
export const getPromptShareServerSideProps: GetServerSideProps<PromptSharePageProps> = async () => {
  try {
    const response = await resilientFetch(
      `${getBackendOrigin()}/prompt_share/api/prompts?limit=${INITIAL_PROMPT_LIMIT}`,
      {
        headers: {
          "Accept": "application/json"
        }
      }
    );
    if (!response.ok) {
      return { props: { initialPrompts: [], initialPagination: null } };
    }

    const data = await response.json() as PromptFeedResponse;
    // APIが制限した初期ページをクライアント側で使いやすい形式に正規化する。
    // Normalize the API-limited initial page into the client-friendly format.
    const initialPrompts = Array.isArray(data.prompts)
      ? data.prompts.map(normalizePromptData)
      : [];

    return { props: { initialPrompts, initialPagination: data.pagination || null } };
  } catch (error) {
    console.error("Failed to load prompt share SSR prompts:", error);
    return { props: { initialPrompts: [], initialPagination: null } };
  }
};
