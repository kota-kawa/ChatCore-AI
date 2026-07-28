import React from "react";
import { useTranslation } from "../../contexts/locale_context";

// メモ機能の概要を表示するコンポーネント
// Component to display the summary of memo features
export function MemoCrawlSummary() {
  const { t } = useTranslation();
  const features = [
    t("memo.crawlFeatureSave"),
    t("memo.crawlFeatureOrganize"),
    t("memo.crawlFeatureExport"),
    t("memo.crawlFeatureShare")
  ];

  return (
    <section className="memo-crawl-summary" aria-labelledby="memo-crawl-summary-title">
      <div className="memo-crawl-summary__content">
        <p className="memo-crawl-summary__eyebrow">Notebook</p>
        <h2 id="memo-crawl-summary-title">{t("memo.crawlTitle")}</h2>
        <p>{t("memo.crawlDescription")}</p>
      </div>
      <ul className="memo-crawl-summary__list" aria-label={t("memo.crawlFeaturesLabel")}>
        {features.map((feature) => (
          <li key={feature}>
            <i className="bi bi-check2-circle" aria-hidden="true"></i>
            <span>{feature}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
