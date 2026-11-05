// プロンプト共有のカテゴリ別一覧ページ（/prompt_share/category/[category]）。SSRで一覧とSEO文言を取得して描画コンポーネントに渡す。
// Category-specific prompt library page (/prompt_share/category/[category]); fetches the list and SEO copy at SSR and hands them to the view component.
import type { GetServerSideProps } from "next";

import {
  PromptCategoryPage,
  type PromptCategoryPageViewProps
} from "../../../components/prompt_share/prompt_category_page";
import {
  getPromptCategoryServerSideProps,
  type PromptCategoryPageProps
} from "../../../components/prompt_share/prompt_share_page_data";
import { getPromptCategorySeoCopy } from "../../../components/prompt_share/prompt_category_seo";
import { resolvePageLocale } from "../../../lib/i18n/config";

// 一覧の事前取得は共通処理に任せ、このページではロケールに応じたSEO文言を足す。文言が無いカテゴリは404にする
// Delegate list pre-fetching to the shared helper and add locale-specific SEO copy here; categories without copy return 404
export const getServerSideProps: GetServerSideProps<PromptCategoryPageViewProps> = async (context) => {
  const result = await getPromptCategoryServerSideProps(context);
  if (!("props" in result)) {
    return result;
  }

  const props = await result.props;
  const locale = resolvePageLocale(context.locale, context.req.headers.cookie, context.req.headers["accept-language"]);
  const copy = getPromptCategorySeoCopy(props.category, locale);
  if (!copy) {
    return { notFound: true };
  }

  return {
    props: {
      ...props,
      copy
    }
  };
};

// Next.jsのページ本体。表示はPromptCategoryPageコンポーネントに委ねる
// Next.js page entry; rendering is delegated to the PromptCategoryPage component
export default function PromptCategoryPageEntry(props: PromptCategoryPageViewProps) {
  return <PromptCategoryPage {...props} />;
}

// SSR用のprops型を、このページ経由でも参照できるよう再エクスポートする
// Re-export the SSR props type so it can also be referenced through this page
export type { PromptCategoryPageProps };
