import { useTranslation } from "../../contexts/locale_context";

// 3ステップの利用フロー。どこからアカウントが必要になるかも明記する
// Three-step flow, stating where an account starts being required
type Step = { title: string; description: string };

const STEPS_JA: Step[] = [
  {
    title: "一覧から絞り込む",
    description:
      "プロンプト共有ページを開き、カテゴリ・形式・生成対象で候補を絞ります。ここまではアカウントなしで使えます。"
  },
  {
    title: "中身を読んで見極める",
    description:
      "カードを開くと、本文の全文と入力例・出力例、想定モデル、ほかの人のコメントが読めます。"
  },
  {
    title: "チャットで使う",
    description:
      "「チャットで使う」を押すと、ChatCore-AIのチャットにタスクとして並びます。次からは選ぶだけで呼び出せます（無料アカウントが必要）。"
  }
];

const STEPS_EN: Step[] = [
  {
    title: "Filter the feed",
    description:
      "Open the prompt sharing page and narrow it by category, format, and output type. No account needed this far."
  },
  {
    title: "Read it before you commit",
    description:
      "Open a card to see the full body, input and output examples, the intended model, and other people's comments."
  },
  {
    title: "Use it in chat",
    description:
      "Press “Use in chat” and the prompt joins your task list in ChatCore-AI, ready to pick next time. A free account is required for this step."
  }
];

const OPERATION_JA: Step[] = [
  {
    title: "コメントは荒らしにくくしてあります",
    description: "リンクの貼りすぎと短時間の連投を制限しています。気になるコメントは報告でき、自分のコメントはいつでも削除できます。"
  },
  {
    title: "投稿はあとから直せます",
    description: "公開したプロンプトやSKILLは、管理画面から編集・削除できます。書き直しを前提に、まず出して構いません。"
  },
  {
    title: "共有はリンク1本です",
    description: "投稿ごとに固定のURLがあります。ログインしていない相手にもそのまま渡せます。"
  }
];

const OPERATION_EN: Step[] = [
  {
    title: "Comments are hard to flood",
    description:
      "Excessive links and rapid-fire posting are rate limited. You can report a comment, and you can delete your own at any time."
  },
  {
    title: "Posts stay editable",
    description:
      "Published prompts and SKILLs can be edited or deleted from your management page, so publishing early is safe."
  },
  {
    title: "Sharing is one link",
    description: "Every post has a stable URL that works for people who are not signed in."
  }
];

const PRICING_JA: Step[] = [
  { title: "料金", description: "無料です。クレジットカードの登録はありません。" },
  { title: "アカウントなしでできること", description: "公開プロンプトとSKILLの閲覧・検索、リンクからの参照。" },
  {
    title: "無料アカウントが要ること",
    description: "投稿、いいね、コメント、保存、「チャットで使う」。登録はメールアドレスまたはGoogleでできます。"
  }
];

const PRICING_EN: Step[] = [
  { title: "Price", description: "Free. No credit card is involved." },
  { title: "Without an account", description: "Browse and search public prompts and SKILLs, and open shared links." },
  {
    title: "With a free account",
    description: "Post, like, comment, save, and use prompts in chat. Sign up with an email address or with Google."
  }
];

export function PromptShareLpUsage() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const steps = isEn ? STEPS_EN : STEPS_JA;
  const operation = isEn ? OPERATION_EN : OPERATION_JA;
  const pricing = isEn ? PRICING_EN : PRICING_JA;
  return (
    <section id="usage" className="lp-section" aria-labelledby="pslp-usage-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "HOW IT WORKS" : "使い方"}</p>
        <h2 id="pslp-usage-heading" className="lp-heading">
          {isEn ? (
            <>From the feed to your chat in three steps.</>
          ) : (
            <>
              一覧からチャットまで、
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

        <div className="pslp-split pslp-split--spaced">
          <div className="pslp-panel">
            <h3 className="pslp-panel__title">{isEn ? "How it is kept usable" : "荒れないための仕組み"}</h3>
            <dl className="pslp-panel__list">
              {operation.map((item) => (
                <div key={item.title} className="pslp-panel__row">
                  <dt>{item.title}</dt>
                  <dd>{item.description}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="pslp-panel">
            <h3 className="pslp-panel__title">{isEn ? "Price and prerequisites" : "料金と前提"}</h3>
            <dl className="pslp-panel__list">
              {pricing.map((item) => (
                <div key={item.title} className="pslp-panel__row">
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
