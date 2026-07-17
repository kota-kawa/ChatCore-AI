// 利用開始までの3ステップ（実際の手順なので番号付きで表現する）
// Three steps to get started (numbered because it is a real sequence)
const LP_FLOW_STEPS = [
  {
    title: "アカウントを登録する",
    description: "メールアドレスがあれば数分で完了します。登録も利用も無料です。"
  },
  {
    title: "AIに話しかける",
    description: "調べたいこと、書きたいことを日本語でそのまま入力します。"
  },
  {
    title: "残して、共有する",
    description: "良い回答はメモへ保存、良い聞き方はプロンプトとして共有します。"
  }
] as const;

// 利用フローセクション
// Usage flow section
export function LpFlow() {
  return (
    <section id="flow" className="lp-section lp-flow" aria-labelledby="lp-flow-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">使い方</p>
        <h2 id="lp-flow-heading" className="lp-heading">
          始め方はかんたん、3ステップ。
        </h2>
        <ol className="lp-flow__list">
          {LP_FLOW_STEPS.map((step, index) => (
            <li key={step.title} className="lp-flow__step">
              <span className="lp-flow__number" aria-hidden="true">
                {index + 1}
              </span>
              <h3 className="lp-flow__title">{step.title}</h3>
              <p className="lp-flow__description">{step.description}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
