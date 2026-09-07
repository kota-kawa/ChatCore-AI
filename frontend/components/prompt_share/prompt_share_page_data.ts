import type { GetServerSideProps } from "next";

import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { normalizePromptData } from "../../scripts/prompt_share/formatters";
import type {
  PromptData,
  PromptFeedResponse,
  PromptPagination
} from "../../scripts/prompt_share/types";
import { localizedAbsoluteUrl } from "../../lib/seo";
import { resolvePageLocale, type Locale } from "../../lib/i18n/config";
import { promptShareText } from "../../scripts/prompt_share/i18n";
import {
  normalizeCategory,
  PROMPT_CATEGORY_KEYS
} from "../../scripts/prompt_share/prompt_category_registry";

export type PromptSharePageProps = {
  initialPrompts?: PromptData[];
  initialPagination?: PromptPagination | null;
  initialCategory?: string;
};

export type PromptCategoryPageProps = {
  category: string;
  initialPrompts: PromptData[];
  initialPagination: PromptPagination | null;
  initialLoadFailed: boolean;
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

type InitialPromptData = {
  initialPrompts: PromptData[];
  initialPagination: PromptPagination | null;
  initialLoadFailed: boolean;
};

// 公開フィードの先頭ページをSSRで取得する。カテゴリページと共有トップで同じ取得境界を使う。
// Fetch the first public-feed page during SSR so category pages and the main feed share one boundary.
export async function fetchInitialPromptData(category?: string, locale?: Locale): Promise<InitialPromptData> {
  const params = new URLSearchParams({ limit: String(INITIAL_PROMPT_LIMIT) });
  if (category) {
    params.set("category", category);
  }

  try {
    const response = await resilientFetch(
      `${getBackendOrigin()}/prompt_share/api/prompts?${params.toString()}`,
      {
        headers: {
          "Accept": "application/json",
          ...(locale ? { "Accept-Language": locale } : {})
        }
      }
    );
    if (!response.ok) {
      return { initialPrompts: [], initialPagination: null, initialLoadFailed: true };
    }

    const data = await response.json() as PromptFeedResponse;
    return {
      initialPrompts: Array.isArray(data.prompts)
        ? data.prompts.map(normalizePromptData)
        : [],
      initialPagination: data.pagination || null,
      initialLoadFailed: false
    };
  } catch (error) {
    console.error("Failed to load prompt share SSR prompts:", error);
    return { initialPrompts: [], initialPagination: null, initialLoadFailed: true };
  }
}

// SSR時にプロンプト一覧を事前取得する。失敗した場合でも空配列でページを返し、CSRで再取得させる
// Pre-fetches the prompt list at SSR time; returns an empty array on failure so the client can retry
export const getPromptShareServerSideProps: GetServerSideProps<PromptSharePageProps> = async (context) => {
  const rawCategory = context.query?.category;
  const requestedCategory = Array.isArray(rawCategory) ? "" : String(rawCategory || "").trim().toLowerCase();
  const normalizedCategory = normalizeCategory(requestedCategory);
  const category = normalizedCategory && PROMPT_CATEGORY_KEYS.includes(normalizedCategory)
    ? normalizedCategory
    : undefined;
  const requestHeaders = context.req?.headers;
  const locale = resolvePageLocale(
    context.locale,
    requestHeaders?.cookie,
    requestHeaders?.["accept-language"]
  );
  const data = await fetchInitialPromptData(category, locale);
  return {
    props: {
      initialPrompts: data.initialPrompts,
      initialPagination: data.initialPagination,
      initialCategory: category || "all"
    }
  };
};

// 正規カテゴリキーだけを受け付け、旧ラベルや大文字の重複URLを作らない。
// Accept only exact canonical keys so legacy labels and case variants cannot become duplicate URLs.
export const getPromptCategoryServerSideProps: GetServerSideProps<PromptCategoryPageProps> = async (context) => {
  const rawCategory = context.params?.category;
  const category = Array.isArray(rawCategory) ? "" : String(rawCategory || "").trim();

  if (!category || !PROMPT_CATEGORY_KEYS.includes(category)) {
    return { notFound: true };
  }

  const requestHeaders = context.req?.headers;
  const locale = resolvePageLocale(
    context.locale,
    requestHeaders?.cookie,
    requestHeaders?.["accept-language"]
  );
  const data = await fetchInitialPromptData(category, locale);
  return {
    props: {
      category,
      initialPrompts: data.initialPrompts,
      initialPagination: data.initialPagination,
      initialLoadFailed: data.initialLoadFailed
    }
  };
};
