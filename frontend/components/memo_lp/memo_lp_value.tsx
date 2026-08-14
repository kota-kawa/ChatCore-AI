import { useTranslation } from "../../contexts/locale_context";

// 「残す・整える・見返す」の3つに絞り、メモ画面に実在する操作だけを並べる。
// 文言は frontend/lib/i18n/catalogs/ja.ts の実ラベルに合わせる。
// Three verbs (capture, organize, revisit) listing only actions that exist on the memo screen.
// The wording follows the real UI labels in frontend/lib/i18n/catalogs/ja.ts.
type ValueItem = {
  title: string;
  description: string;
  points: string[];
};

const VALUE_ITEMS_JA: ValueItem[] = [
  {
    title: "残す",
    description:
      "チャットの回答も、自分で書いた文章も、同じ一覧に入ります。タイトルを空にしておけば、本文の1行目がタイトルになります。",
    points: [
      "チャットの回答をブックマークのボタンでメモにする",
      "メモ画面で直接書く（タイトル＋本文、Markdown）",
      "「AIタイトル」で本文からタイトルを提案してもらう",
      "背景色を8色（レモン・アンバー・ミントなど）から選ぶ"
    ]
  },
  {
    title: "整える",
    description:
      "増えても迷わないように、コレクション・ピン留め・アーカイブの3つで置き場所を決められます。",
    points: [
      "コレクションに分ける（名前と色を自分で決める）",
      "ピン留めして一覧の先頭に固定する",
      "アーカイブして、ふだんの一覧から外す",
      "一括操作で、選んだメモをまとめてピン留め・アーカイブ・コレクション設定する",
      "並び順は手動順・新しい順・更新順・古い順・タイトル順から選ぶ"
    ]
  },
  {
    title: "見返す",
    description:
      "探して、開いて、そのまま直せます。詳細画面の編集は入力が止まると自動で保存されます。",
    points: [
      "タイトルと本文のキーワードで検索する",
      "「AI類似検索」で、言い回しが違っても近いメモを探す",
      "編集とプレビューを切り替えながらMarkdownを直す",
      "メモ専用のAIに要約・重要ポイント・誤字修正・書き直しを頼む",
      "Markdown・JSON・CSVで書き出す／共有リンクで1件だけ渡す"
    ]
  }
];

const VALUE_ITEMS_EN: ValueItem[] = [
  {
    title: "Capture",
    description:
      "Chat answers and things you write yourself land in the same list. Leave the title empty and the first line of the body becomes the title.",
    points: [
      "Turn a chat answer into a memo with the bookmark button",
      "Write directly on the memo screen (title plus Markdown body)",
      "Ask “AI title” to suggest a title from the body",
      "Pick a background colour from eight (lemon, amber, mint, and more)"
    ]
  },
  {
    title: "Organize",
    description:
      "Collections, pins, and the archive decide where a memo lives, so a growing list stays navigable.",
    points: [
      "Sort memos into collections you name and colour yourself",
      "Pin a memo to the top of the list",
      "Archive a memo to take it out of the everyday list",
      "Use bulk actions to pin, archive, or set a collection on many memos at once",
      "Order by manual, newest, recently updated, oldest, or title"
    ]
  },
  {
    title: "Revisit",
    description:
      "Search, open, and edit in place. Edits in the detail view autosave once you stop typing.",
    points: [
      "Search titles and bodies by keyword",
      "Use “AI similarity” search to find near matches with different wording",
      "Switch between edit and preview while you rewrite the Markdown",
      "Ask the memo's own AI to summarize, list key points, proofread, or rewrite",
      "Export as Markdown, JSON, or CSV, or hand over a single memo as a share link"
    ]
  }
];

export function MemoLpValue() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? VALUE_ITEMS_EN : VALUE_ITEMS_JA;
  return (
    <section id="value" className="lp-section mslp-value" aria-labelledby="mslp-value-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT YOU CAN DO" : "できること"}</p>
        <h2 id="mslp-value-heading" className="lp-heading">
          {isEn ? (
            <>Capture it, organize it, come back to it.</>
          ) : (
            <>
              残して、整えて、
              <br className="lp-br-sp" />
              見返す。
            </>
          )}
        </h2>
        <div className="mslp-value__grid">
          {items.map((item) => (
            <article key={item.title} className="mslp-value__item">
              <h3 className="mslp-value__title">{item.title}</h3>
              <p className="mslp-value__description">{item.description}</p>
              <ul className="mslp-value__points">
                {item.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
