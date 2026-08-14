import { useTranslation } from "../../contexts/locale_context";

// メモ紹介ページのFAQ。JSON-LDと表示の両方でこのデータを使う
// FAQ for the memo landing page; this data feeds both JSON-LD and the visible UI
export const MEMO_LP_FAQ_ITEMS = [
  {
    question: "メモはほかの人に見られますか？",
    answer:
      "自分のメモは自分のアカウントからしか開けません。ほかの人が読めるのは、共有リンクを作ったメモだけです。共有ページに出るのはそのメモのタイトル・保存日時・本文だけで、あなたの名前やほかのメモ、コレクションは出ません。"
  },
  {
    question: "共有リンクはいつまで有効ですか？",
    answer:
      "メモ画面から作る共有リンクは30日で期限切れになり、それ以降はページが開けなくなります。共有を途中で取り消すボタンはまだないので、それより早く止めたいときはメモごと削除してください。削除すると共有リンクも同時に無効になります。"
  },
  {
    question: "編集した内容は元に戻せますか？",
    answer:
      "戻せません。詳細画面の編集は入力が止まると自動保存され、前の版は残りません。大きく書き換える前に「全文をコピー」やエクスポートで控えを取っておいてください。"
  },
  {
    question: "どんな形式で書き出せますか？",
    answer:
      "Markdown・JSON・CSVの3形式です。表示中のメモをまとめて書き出すか、選んだメモだけを書き出すかを選べます。"
  },
  {
    question: "ほかのAIツールからメモを作れますか？",
    answer:
      "MCPに対応したクライアントを接続すると、メモの一覧・検索・コレクション一覧の取得と、作成・更新・末尾への追記ができます。1件の本文は20,000文字まで、書き込みは1時間に60回までです。"
  }
] as const;

export const MEMO_LP_FAQ_ITEMS_EN = [
  {
    question: "Can other people see my memos?",
    answer:
      "Your memos open only from your own account. The only ones anyone else can read are those you have created a share link for, and that page shows just the memo's title, saved time, and body — not your name, your other memos, or your collections."
  },
  {
    question: "How long does a share link stay valid?",
    answer:
      "A share link created from the memo screen expires after 30 days, after which the page no longer opens. There is no revoke button yet, so to stop sharing sooner, delete the memo; deleting it also invalidates the link."
  },
  {
    question: "Can I undo an edit?",
    answer:
      "No. Edits in the detail view autosave once you stop typing, and no earlier version is kept. Before a large rewrite, take a copy with “Copy full text” or an export."
  },
  {
    question: "What formats can I export to?",
    answer:
      "Markdown, JSON, and CSV. You can export everything currently listed, or only the memos you select."
  },
  {
    question: "Can another AI tool create memos for me?",
    answer:
      "Connect an MCP-capable client and it can list, search, and read your collections, and create, update, or append to memos. A body is capped at 20,000 characters and writes at 60 per hour."
  }
] as const;

export function MemoLpFaq() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? MEMO_LP_FAQ_ITEMS_EN : MEMO_LP_FAQ_ITEMS;
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby="mslp-faq-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "FREQUENTLY ASKED QUESTIONS" : "よくある質問"}</p>
        <h2 id="mslp-faq-heading" className="lp-heading">
          {isEn ? (
            <>Questions people ask before they trust it.</>
          ) : (
            <>
              預ける前に、
              <br className="lp-br-sp" />
              よく聞かれること。
            </>
          )}
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
