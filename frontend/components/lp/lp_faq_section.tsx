// 紹介ページ（LP）4 本が共有する、よくある質問セクションの描画。見出しの文言・id・質問データは各 LP が渡す。
// Shared rendering of the FAQ section for the four landing pages; each page passes its heading, heading id and question data.
import type { ReactNode } from "react";
import { useTranslation } from "../../contexts/locale_context";

type LpFaqSectionItem = {
  readonly question: string;
  readonly answer: string;
};

type LpFaqSectionProps = {
  headingId: string;
  heading: ReactNode;
  items: readonly LpFaqSectionItem[];
};

// 見出し・目印の文言を props で受け、質問と答えを <dl> で一覧表示するセクション
// Section that takes the heading via props and lists the questions and answers as a <dl>
export function LpFaqSection({ headingId, heading, items }: LpFaqSectionProps) {
  const { locale } = useTranslation();
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby={headingId}>
      <div className="lp-container">
        <p className="lp-eyebrow">{locale === "en" ? "FREQUENTLY ASKED QUESTIONS" : "よくある質問"}</p>
        <h2 id={headingId} className="lp-heading">
          {heading}
        </h2>
        <dl className="lp-faq__list">
          {items.map((item) => (
            <div key={item.question} className="lp-faq__item">
              <dt className="lp-faq__question">{item.question}</dt>
              <dd className="lp-faq__answer">{item.answer}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
