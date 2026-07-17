import type { ReactNode } from "react";

import { LpFooter } from "../lp/lp_footer";
import { LpHeader } from "../lp/lp_header";

// 要点サマリーカード1枚分の型 / Type for a single plain-language summary card
export type LegalSummaryItem = {
  icon: string;
  title: string;
  text: string;
};

// 条文セクション1つ分の型 / Type for a single article section
export type LegalSection = {
  id: string;
  number: string;
  heading: string;
  body: ReactNode;
};

type LegalDocumentProps = {
  kicker: string;
  eyebrow: string;
  title: string;
  lead: string;
  meta: string[];
  summaryLabel: string;
  summary: LegalSummaryItem[];
  summaryNote: string;
  sections: LegalSection[];
};

// プライバシーポリシー・利用規約で共有する法的文書レイアウト
// （ヒーロー → 要点サマリー → 目次付き条文）
// Legal document layout shared by the privacy policy and terms pages
// (hero → plain-language summary → articles with a table of contents)
export function LegalDocument({
  kicker,
  eyebrow,
  title,
  lead,
  meta,
  summaryLabel,
  summary,
  summaryNote,
  sections
}: LegalDocumentProps) {
  return (
    <div className="lp-page docs-page">
      <LpHeader />
      <main>
        <section className="docs-hero">
          <p className="docs-hero__kicker" aria-hidden="true">
            {kicker}
          </p>
          <div className="lp-container">
            <p className="lp-eyebrow">{eyebrow}</p>
            <h1 className="docs-hero__title">{title}</h1>
            <p className="docs-hero__lead">{lead}</p>
            <ul className="docs-hero__meta">
              {meta.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="docs-summary" aria-label={summaryLabel}>
          <div className="lp-container">
            <p className="docs-summary__label">{summaryLabel}</p>
            <ul className="docs-summary__grid">
              {summary.map((item) => (
                <li key={item.title} className="docs-summary__card">
                  <span className="docs-summary__icon" aria-hidden="true">
                    <i className={`bi ${item.icon}`}></i>
                  </span>
                  <span className="docs-summary__title">{item.title}</span>
                  <span className="docs-summary__text">{item.text}</span>
                </li>
              ))}
            </ul>
            <p className="docs-summary__note">{summaryNote}</p>
          </div>
        </section>

        <section className="docs-body">
          <div className="lp-container docs-body__inner">
            <nav className="docs-toc" aria-label="目次">
              <p className="docs-toc__label">目次</p>
              <ol className="docs-toc__list">
                {sections.map((section) => (
                  <li key={section.id}>
                    <a href={`#${section.id}`}>
                      {section.number} {section.heading}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
            <article className="docs-article">
              {sections.map((section) => (
                <section key={section.id} id={section.id} className="docs-article__section">
                  <h2 className="docs-article__heading">
                    <span className="docs-article__number">{section.number}</span>
                    {section.heading}
                  </h2>
                  {section.body}
                </section>
              ))}
            </article>
          </div>
        </section>
      </main>
      <LpFooter />
    </div>
  );
}
