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

export default function PromptCategoryPageEntry(props: PromptCategoryPageViewProps) {
  return <PromptCategoryPage {...props} />;
}

export type { PromptCategoryPageProps };
