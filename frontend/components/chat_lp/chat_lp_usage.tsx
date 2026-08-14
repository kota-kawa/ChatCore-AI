import { useTranslation } from "../../contexts/locale_context";

// 3ステップの利用フローと、その下に「頼み方のこつ」「料金と前提」の2カラムを置く
// Three-step flow, followed by two columns: how to ask, and price and prerequisites
type Step = { title: string; description: string };

const STEPS_JA: Step[] = [
  {
    title: "やりたいことを書く",
    description:
      "トップページの入力欄に、状況をそのまま書きます。ここまではログインなしで使えます。必要なら文書やコードのファイルも添えられます。"
  },
  {
    title: "タスクを押す、またはそのまま送る",
    description:
      "近いタスクカードがあれば押します。カードの指示と入力欄の内容がまとめて送られます。当てはまるものが無ければ、そのまま送信してかまいません。"
  },
  {
    title: "返ってきたものを残す",
    description:
      "回答はメモに保存したり、リンクで共有したり、再生成して別案と見比べたりできます（保存・共有には無料アカウントが必要です）。"
  }
];

const STEPS_EN: Step[] = [
  {
    title: "Write what you need",
    description:
      "Type your situation into the box on the home page. No account is needed this far, and you can attach document or code files if they help."
  },
  {
    title: "Press a task, or just send it",
    description:
      "If a task card fits, press it: the card's instructions and whatever you typed are sent together. If none fits, send the message as it is."
  },
  {
    title: "Keep what came back",
    description:
      "Save an answer as a memo, share it as a link, or regenerate it to compare alternatives. Saving and sharing need a free account."
  }
];

const ASKING_JA: Step[] = [
  {
    title: "動くUIが欲しいとき",
    description: "「グラフで」「図解して」「インタラクティブに」と明示します。頼まなければ文章で返ります。"
  },
  {
    title: "3Dが欲しいとき",
    description: "「3Dで」「立体で」「Three.jsで」と書きます。描かれた立体はドラッグで視点を回せます。"
  },
  {
    title: "文章だけで欲しいとき",
    description: "「テキストだけ」「図は不要」と添えると、UIを出さずに文章で答えます。"
  }
];

const ASKING_EN: Step[] = [
  {
    title: "When you want a working UI",
    description: "Say “as a chart”, “as a diagram”, or “make it interactive”. Without asking, you get prose."
  },
  {
    title: "When you want 3D",
    description: "Say “in 3D”, “as a solid”, or “with Three.js”. You can drag to orbit whatever it builds."
  },
  {
    title: "When you want text only",
    description: "Add “text only” or “no diagram” and it answers in prose without building a UI."
  }
];

const PRICING_JA: Step[] = [
  { title: "料金", description: "無料です。クレジットカードの登録はありません。" },
  {
    title: "ログインなしでできること",
    description: "メッセージの送信、最初から入っているタスクカードの利用、生成UIの表示。1日に送れる回数に上限があり、会話は履歴に残りません。"
  },
  {
    title: "無料アカウントでできること",
    description: "履歴の保存、タスクの作成・編集・並び替え、メモ保存、共有リンクの作成、プロジェクトでのまとめ。登録はメールアドレスまたはGoogleでできます。"
  }
];

const PRICING_EN: Step[] = [
  { title: "Price", description: "Free. No credit card is involved." },
  {
    title: "Without an account",
    description: "Send messages, use the preloaded task cards, and view generated UIs. The daily message count is capped and nothing is kept in history."
  },
  {
    title: "With a free account",
    description: "Keep your history, create and reorder your own tasks, save memos, create share links, and group chats into projects. Sign up with an email address or with Google."
  }
];

export function ChatLpUsage() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const steps = isEn ? STEPS_EN : STEPS_JA;
  const asking = isEn ? ASKING_EN : ASKING_JA;
  const pricing = isEn ? PRICING_EN : PRICING_JA;
  return (
    <section id="usage" className="lp-section" aria-labelledby="cslp-usage-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "HOW IT WORKS" : "使い方"}</p>
        <h2 id="cslp-usage-heading" className="lp-heading">
          {isEn ? (
            <>Type it, press it, keep the result.</>
          ) : (
            <>
              書いて、押して、
              <br className="lp-br-sp" />
              受け取るだけ。
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

        <div className="cslp-split cslp-split--spaced">
          <div className="cslp-panel">
            <h3 className="cslp-panel__title">{isEn ? "How to ask" : "頼み方のこつ"}</h3>
            <dl className="cslp-panel__list">
              {asking.map((item) => (
                <div key={item.title} className="cslp-panel__row">
                  <dt>{item.title}</dt>
                  <dd>{item.description}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="cslp-panel">
            <h3 className="cslp-panel__title">{isEn ? "Price and prerequisites" : "料金と前提"}</h3>
            <dl className="cslp-panel__list">
              {pricing.map((item) => (
                <div key={item.title} className="cslp-panel__row">
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
