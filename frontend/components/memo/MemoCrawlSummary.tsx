import React from "react";

// メモ機能の概要を表示するコンポーネント
// Component to display the summary of memo features
export function MemoCrawlSummary() {
  const features = [
    "AIチャットの回答をメモとして保存",
    "タイトル、本文、コレクションで検索・整理",
    "Markdown、JSON、CSV形式でエクスポート",
    "共有リンクで必要なメモだけ公開"
  ];

  return (
    <section className="memo-crawl-summary" aria-labelledby="memo-crawl-summary-title">
      <div className="memo-crawl-summary__content">
        <p className="memo-crawl-summary__eyebrow">Notebook</p>
        <h2 id="memo-crawl-summary-title">AIとの作業ログを整理するノート画面</h2>
        <p>
          Chat Coreのメモ画面では、AIチャットで得た回答や作業中のアイデアを保存し、
          後から検索、編集、コレクション管理、共有、エクスポートができます。
        </p>
      </div>
      <ul className="memo-crawl-summary__list" aria-label="メモ画面でできること">
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
