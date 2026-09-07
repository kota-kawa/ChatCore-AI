import type { ReactNode } from "react";

import { LpFooter } from "../lp/lp_footer";
import { PromptShareLpHeader } from "../prompt_share_lp/prompt_share_lp_header";
import { SeoHead } from "../SeoHead";
import { useTranslation } from "../../contexts/locale_context";
import type { Locale } from "../../lib/i18n/config";
import {
  localizePublicPath,
  localizedAbsoluteUrl,
  truncateSeoText
} from "../../lib/seo";
import { buildPromptPath } from "../../lib/promptSlug";
import { stripMarkdownForPreview } from "../../scripts/core/markdown_preview";
import {
  getCategoryLabel,
  PROMPT_CATEGORY_KEYS
} from "../../scripts/prompt_share/prompt_category_registry";
import { normalizePromptData } from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";
import {
  getPromptCategoryPath,
  type PromptCategorySeoCopy
} from "./prompt_category_seo";

export type PromptCategoryPageViewProps = {
  category: string;
  initialPrompts: PromptData[];
  initialLoadFailed: boolean;
  copy: PromptCategorySeoCopy;
};

function getPromptCategoryFeedPath(category: string, locale: Locale) {
  return localizePublicPath(`/prompt_share?category=${encodeURIComponent(category)}`, locale);
}

function getPromptDetailPath(prompt: PromptData, locale: Locale) {
  if (prompt.id === undefined || prompt.id === null || prompt.id === "") return "";
  return localizePublicPath(buildPromptPath(prompt.id, prompt.title), locale);
}

function getPromptPreview(prompt: PromptData) {
  const source = prompt.description?.trim() || stripMarkdownForPreview(prompt.content || "");
  return truncateSeoText(source, 180);
}

function PromptCategoryPromptCard({ prompt, locale, viewLabel, categoryFallback, untitledLabel }: {
  prompt: PromptData;
  locale: Locale;
  viewLabel: string;
  categoryFallback: string;
  untitledLabel: string;
}) {
  const href = getPromptDetailPath(prompt, locale);
  if (!href) return null;
  const title = prompt.title?.trim() || untitledLabel;
  const preview = getPromptPreview(prompt);
  const categoryLabel = getCategoryLabel(prompt.category, locale) || categoryFallback;
  return (
    <li className="prompt-category-prompts__item">
      <a href={href} className="prompt-category-prompt-card">
        <span className="prompt-category-prompt-card__category">{categoryLabel}</span>
        <h3>{title}</h3>
        {preview ? <p>{preview}</p> : null}
        <span className="prompt-category-prompt-card__link">{viewLabel} <span aria-hidden="true">→</span></span>
      </a>
    </li>
  );
}

export function buildPromptCategoryStructuredData(
  category: string,
  locale: Locale,
  copy: PromptCategorySeoCopy,
  prompts: readonly PromptData[]
) {
  const pageUrl = localizedAbsoluteUrl(getPromptCategoryPath(category, locale), locale);
  const homeUrl = localizedAbsoluteUrl("/", locale);
  const feedUrl = localizedAbsoluteUrl("/prompt_share", locale);
  const categoryLabel = getCategoryLabel(category, locale);
  const itemList = prompts
    .map((prompt) => {
      if (prompt.id === undefined || prompt.id === null || prompt.id === "") return null;
      const promptPath = buildPromptPath(prompt.id, prompt.title);
      return {
        "@type": "ListItem",
        position: 0,
        name: prompt.title,
        url: localizedAbsoluteUrl(promptPath, locale)
      };
    })
    .filter((item): item is { "@type": string; position: number; name: string; url: string } => item !== null)
    .map((item, index) => ({ ...item, position: index + 1 }));

  return [
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: copy.heading,
      url: pageUrl,
      description: copy.description,
      inLanguage: locale,
      about: categoryLabel,
      isPartOf: {
        "@type": "WebSite",
        name: "Chat Core",
        url: homeUrl
      },
      mainEntity: {
        "@type": "ItemList",
        numberOfItems: itemList.length,
        itemListElement: itemList
      }
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: locale === "en" ? "Home" : "ホーム", item: homeUrl },
        { "@type": "ListItem", position: 2, name: locale === "en" ? "Prompt library" : "プロンプト共有", item: feedUrl },
        { "@type": "ListItem", position: 3, name: categoryLabel, item: pageUrl }
      ]
    }
  ];
}

function Section({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`prompt-category-section${className ? ` ${className}` : ""}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function PromptCategoryPage({
  category,
  initialPrompts,
  initialLoadFailed,
  copy
}: PromptCategoryPageViewProps) {
  const { locale, t } = useTranslation();
  const categoryLabel = getCategoryLabel(category, locale);
  const pageUrl = getPromptCategoryPath(category, locale);
  const feedUrl = getPromptCategoryFeedPath(category, locale);
  const structuredData = buildPromptCategoryStructuredData(category, locale, copy, initialPrompts);
  const otherCategories = PROMPT_CATEGORY_KEYS.filter((key) => key !== category);

  return (
    <>
      <SeoHead
        title={copy.title}
        description={copy.description}
        canonicalPath={pageUrl}
        structuredData={structuredData}
      >
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/prompt_share_category/prompt_share_category.css" />
      </SeoHead>

      <div className="lp-page prompt-category-page">
        <PromptShareLpHeader />
        <main className="prompt-category-page__main">
          <nav className="prompt-category-breadcrumbs" aria-label={locale === "en" ? "Breadcrumb" : "パンくずリスト"}>
            <a href={localizedAbsoluteUrl("/", locale)}>{locale === "en" ? "Home" : "ホーム"}</a>
            <span aria-hidden="true">/</span>
            <a href={localizedAbsoluteUrl("/prompt_share", locale)}>{t("nav.promptShare")}</a>
            <span aria-hidden="true">/</span>
            <span aria-current="page">{categoryLabel}</span>
          </nav>

          <header className="prompt-category-hero">
            <p className="prompt-category-hero__eyebrow">{t("promptShare.categoryGuides")}</p>
            <h1>{copy.heading}</h1>
            <p className="prompt-category-hero__description">{copy.intro}</p>
            <a href={feedUrl} className="lp-btn lp-btn--primary prompt-category-hero__cta">{t("promptShare.categoryPageBrowseAll")}</a>
          </header>

          <Section title={copy.examplesHeading} className="prompt-category-examples">
            <ul>
              {copy.examples.map((example) => <li key={example}>{example}</li>)}
            </ul>
          </Section>

          <Section title={copy.tipHeading} className="prompt-category-tip">
            <p>{copy.tip}</p>
          </Section>

          <Section title={t("promptShare.categoryPagePrompts", { category: categoryLabel })} className="prompt-category-prompts">
            {initialLoadFailed ? (
              <p className="prompt-category-message prompt-category-message--error">{t("promptShare.categoryPageLoadFailed")}</p>
            ) : initialPrompts.length === 0 ? (
              <p className="prompt-category-message">{t("promptShare.categoryPageEmpty")}</p>
            ) : (
              <ul className="prompt-category-prompts__grid">
                {initialPrompts.map((prompt) => (
                  <PromptCategoryPromptCard
                    key={`${prompt.id ?? prompt.title}`}
                    prompt={normalizePromptData(prompt)}
                    locale={locale}
                    viewLabel={t("promptShare.categoryPageViewPrompt")}
                    categoryFallback={categoryLabel}
                    untitledLabel={t("promptShare.untitled")}
                  />
                ))}
              </ul>
            )}
            {initialPrompts.length > 0 ? (
              <a href={feedUrl} className="prompt-category-more-link">{t("promptShare.categoryPageMorePrompts")} <span aria-hidden="true">→</span></a>
            ) : null}
          </Section>

          <Section title={t("promptShare.categoryPageAllCategories")} className="prompt-category-links">
            <ul>
              {otherCategories.map((otherCategory) => (
                <li key={otherCategory}><a href={getPromptCategoryPath(otherCategory, locale)}>{getCategoryLabel(otherCategory, locale)}</a></li>
              ))}
            </ul>
          </Section>

          <p className="prompt-category-page__back-link"><a href={localizedAbsoluteUrl("/prompt_share", locale)}>← {t("nav.promptShare")}</a></p>
        </main>
        <LpFooter />
      </div>
    </>
  );
}
