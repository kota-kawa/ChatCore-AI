import { useTranslation } from "../../contexts/locale_context";

// 3ステップの利用フローと、その下に「AIに任せられること」「料金と前提」の2カラムを置く
// Three-step flow, followed by two columns: what the AI does, and price and prerequisites
type Step = { title: string; description: string };

const STEPS_JA: Step[] = [
  {
    title: "チャットの回答を保存する",
    description:
      "残したい回答の下にあるブックマークのボタンを押すと、その場でメモになります。タイトルを空にしておけば、本文の1行目がそのままタイトルになります。"
  },
  {
    title: "探して、そのまま直す",
    description:
      "メモ画面で検索・並び替え・コレクションから目的のメモを開き、Markdownのまま書き直します。入力が止まると自動で保存され、状態は「保存済み」と表示されます。"
  },
  {
    title: "必要なぶんだけ渡す",
    description:
      "共有リンクを作れば、ログインしていない相手もそのメモだけを読めます。手元に残したいときはMarkdown・JSON・CSVで書き出します。"
  }
];

const STEPS_EN: Step[] = [
  {
    title: "Save an answer from a chat",
    description:
      "Press the bookmark button under the answer you want to keep and it becomes a memo right there. Leave the title empty and the first line of the body becomes the title."
  },
  {
    title: "Find it and edit in place",
    description:
      "Open the memo from search, sorting, or a collection, and rewrite it as Markdown. It autosaves once you stop typing and the status reads “Saved”."
  },
  {
    title: "Hand over only what you mean to",
    description:
      "Create a share link and someone signed out can read that memo alone. To keep a copy, export as Markdown, JSON, or CSV."
  }
];

const AI_JA: Step[] = [
  {
    title: "AIタイトル",
    description: "本文からタイトルの案を出します。気に入らなければ、そのまま自分で書き換えられます。"
  },
  {
    title: "メモ専用のAI",
    description:
      "開いているメモの内容を見て、要約・重要ポイントの箇条書き・誤字修正・書き直しに答えます。本文への反映は、実行ボタンを押したときだけです。"
  },
  {
    title: "AI類似検索",
    description:
      "並び順で選ぶと、キーワードが一致しなくても内容の近いメモから並びます。準備ができていないときは通常の検索に切り替わります。"
  }
];

const AI_EN: Step[] = [
  {
    title: "AI title",
    description: "Suggests a title from the body. If you dislike it, overwrite it yourself."
  },
  {
    title: "The memo's own AI",
    description:
      "Reads the memo you have open and answers requests to summarize, list key points, proofread, or rewrite. Nothing reaches the body until you press the run button."
  },
  {
    title: "AI similarity search",
    description:
      "Pick it as the sort order and memos are ranked by how close their content is, even when the keywords differ. It falls back to ordinary search when unavailable."
  }
];

const PRICING_JA: Step[] = [
  { title: "料金", description: "無料です。クレジットカードの登録はありません。" },
  {
    title: "必要なもの",
    description: "無料アカウント（メールアドレスまたはGoogleで登録）。ブラウザだけで使えます。"
  },
  {
    title: "アカウントなしでできること",
    description: "受け取った共有リンクを開いて、そのメモ1件を読むことだけです。"
  },
  {
    title: "ほかのAIツールから使う",
    description:
      "MCPに対応したクライアントを接続すると、list_memos・search_memos・list_memo_collections で読み、create_memo・update_memo・append_memo_content で書けます。"
  }
];

const PRICING_EN: Step[] = [
  { title: "Price", description: "Free. No credit card is involved." },
  {
    title: "What you need",
    description: "A free account (email address or Google). A browser is enough."
  },
  {
    title: "Without an account",
    description: "Opening a share link someone gave you and reading that single memo."
  },
  {
    title: "From other AI tools",
    description:
      "Connect an MCP-capable client and it can read through list_memos, search_memos, and list_memo_collections, and write through create_memo, update_memo, and append_memo_content."
  }
];

export function MemoLpUsage() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const steps = isEn ? STEPS_EN : STEPS_JA;
  const aiItems = isEn ? AI_EN : AI_JA;
  const pricing = isEn ? PRICING_EN : PRICING_JA;
  return (
    <section id="usage" className="lp-section" aria-labelledby="mslp-usage-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "HOW IT WORKS" : "使い方"}</p>
        <h2 id="mslp-usage-heading" className="lp-heading">
          {isEn ? (
            <>From a chat answer to a shared link in three steps.</>
          ) : (
            <>
              回答を残してから渡すまで、
              <br className="lp-br-sp" />
              3ステップ。
            </>
          )}
        </h2>

        <ol className="lp-flow__list">
          {steps.map((step, index) => (
            <li key={step.title} className="lp-flow__step">
              <span className="lp-flow__number" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="lp-flow__title">{step.title}</h3>
              <p className="lp-flow__description">{step.description}</p>
            </li>
          ))}
        </ol>

        <div className="mslp-split mslp-split--spaced">
          <div className="mslp-panel">
            <h3 className="mslp-panel__title">{isEn ? "What the AI handles" : "AIに任せられること"}</h3>
            <dl className="mslp-panel__list">
              {aiItems.map((item) => (
                <div key={item.title} className="mslp-panel__row">
                  <dt>{item.title}</dt>
                  <dd>{item.description}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="mslp-panel">
            <h3 className="mslp-panel__title">{isEn ? "Price and prerequisites" : "料金と前提"}</h3>
            <dl className="mslp-panel__list">
              {pricing.map((item) => (
                <div key={item.title} className="mslp-panel__row">
                  <dt>{item.title}</dt>
                  <dd>{item.description}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </div>
    </section>
  );
}
