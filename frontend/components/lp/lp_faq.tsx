// ランディングページのFAQセクション（JSON-LDと表示の両方でこのデータを使う）
// FAQ section for the landing page (this data feeds both JSON-LD and the visible UI)
export const LP_FAQ_ITEMS = [
  {
    question: "ChatCore-AIは無料で使えますか？",
    answer:
      "はい。アカウント登録も利用も無料です。クレジットカードの登録は必要ありません。"
  },
  {
    question: "どんなことに使えますか？",
    answer:
      "調査・要約・文章作成・アイデア整理など、日々の知的作業に幅広く使えます。会話の成果はメモとして保存し、うまくいったプロンプトは共有して再利用できます。"
  },
  {
    question: "スマートフォンでも使えますか？",
    answer:
      "はい。アプリのインストールは不要で、ブラウザからそのまま利用できます。スマートフォンやタブレットの画面サイズにも対応しています。"
  },
  {
    question: "会話やメモは他の人に見られますか？",
    answer:
      "いいえ。自分で共有リンクを発行しない限り、会話やメモは非公開のままです。共有はワンクリックで発行・停止できます。"
  }
] as const;

// FAQを表示するセクションコンポーネント
// Section component that renders the FAQ
export function LpFaq() {
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby="lp-faq-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">よくある質問</p>
        <h2 id="lp-faq-heading" className="lp-heading">
          始める前に、気になること。
        </h2>
        <dl className="lp-faq__list">
          {LP_FAQ_ITEMS.map((item) => (
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
