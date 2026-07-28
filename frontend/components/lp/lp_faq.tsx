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
export const LP_FAQ_ITEMS_EN = [
  { question: "Is ChatCore-AI free?", answer: "Yes. Creating an account and using the service are free, and no credit card is required." },
  { question: "What can I use it for?", answer: "Use it for research, summaries, writing, and organizing ideas. Save useful answers as memos and reuse effective prompts." },
  { question: "Can I use it on a phone?", answer: "Yes. There is nothing to install; it works directly in modern phone, tablet, and desktop browsers." },
  { question: "Can other people see my chats and memos?", answer: "No. They stay private unless you explicitly create a share link, which you can disable at any time." }
] as const;

// FAQを表示するセクションコンポーネント
// Section component that renders the FAQ
export function LpFaq() {
  const { locale } = useTranslation();
  const items = locale === "en" ? LP_FAQ_ITEMS_EN : LP_FAQ_ITEMS;
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby="lp-faq-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{locale === "en" ? "FREQUENTLY ASKED QUESTIONS" : "よくある質問"}</p>
        <h2 id="lp-faq-heading" className="lp-heading">
          {locale === "en" ? "Questions before you get started." : "始める前に、気になること。"}
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
import { useTranslation } from "../../contexts/locale_context";
