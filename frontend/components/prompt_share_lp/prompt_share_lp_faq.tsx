import { useTranslation } from "../../contexts/locale_context";

// プロンプト共有ページのFAQ。JSON-LDと表示の両方でこのデータを使う
// FAQ for the prompt sharing page; this data feeds both JSON-LD and the visible UI
export const PROMPT_SHARE_LP_FAQ_ITEMS = [
  {
    question: "アカウントがなくても使えますか？",
    answer:
      "公開プロンプトとSKILLの閲覧・検索、共有リンクからの参照はアカウントなしでできます。投稿・いいね・コメント・保存・「チャットで使う」には無料アカウントが必要です。"
  },
  {
    question: "投稿したプロンプトは非公開にできますか？",
    answer:
      "投稿はすべて公開です。非公開の下書きを保存する機能はないため、公開したくない内容は投稿しないでください。公開後の編集・削除は管理画面からいつでもできます。"
  },
  {
    question: "SKILLとプロンプトは何が違いますか？",
    answer:
      "プロンプトは、そのまま貼って使える指示文です。SKILLは目的・手順・ルールをMarkdownで書いた手順パッケージで、参照用の補助ファイルも一緒に載せられます。一覧では形式で絞り込めます。"
  },
  {
    question: "見つけたプロンプトを、ほかのAIツールで使ってもいいですか？",
    answer:
      "本文をコピーして使えます。「チャットで使う」はChatCore-AIのチャットにタスクとして取り込む機能なので、外部のツールで使う場合はコピーしてお使いください。"
  },
  {
    question: "画像生成のプロンプトや、生成した画像も共有できますか？",
    answer:
      "共有できます。生成対象を「画像」にすると、画像生成プロンプトと、そのプロンプトで作成した画像を作例として添付できます（PNG・JPEG・WebP・GIF、1件5MBまで）。動画・音声向けの投稿区分は現時点ではありません。"
  }
] as const;

export const PROMPT_SHARE_LP_FAQ_ITEMS_EN = [
  {
    question: "Can I use it without an account?",
    answer:
      "Browsing and searching public prompts and SKILLs, and opening shared links, work without an account. Posting, liking, commenting, saving, and “Use in chat” need a free account."
  },
  {
    question: "Can I keep a prompt I post private?",
    answer:
      "Every post is public; there is no private draft area, so do not post anything you would not publish. You can edit or delete a post at any time from your management page."
  },
  {
    question: "How is a SKILL different from a prompt?",
    answer:
      "A prompt is a single instruction you paste into a chat. A SKILL is a procedure written in Markdown covering purpose, steps, and rules, and it can carry supporting files. The feed can be filtered by either format."
  },
  {
    question: "Can I use a prompt I found in another AI tool?",
    answer:
      "Yes, copy the body and use it wherever you like. “Use in chat” specifically loads the prompt as a task inside ChatCore-AI, so copying is the route for external tools."
  },
  {
    question: "Can I share image-generation prompts and generated images?",
    answer:
      "Yes. Set the output type to image to share an image-generation prompt and attach an image created with that prompt as an example (PNG, JPEG, WebP, or GIF, up to 5MB each). There is no video or audio category yet."
  }
] as const;

export function PromptShareLpFaq() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? PROMPT_SHARE_LP_FAQ_ITEMS_EN : PROMPT_SHARE_LP_FAQ_ITEMS;
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby="pslp-faq-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "FREQUENTLY ASKED QUESTIONS" : "よくある質問"}</p>
        <h2 id="pslp-faq-heading" className="lp-heading">
          {isEn ? (
            <>Questions people ask before posting.</>
          ) : (
            <>
              投稿する前に、
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
