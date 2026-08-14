import { useTranslation } from "../../contexts/locale_context";

// 「探す・使う・出す」の3つに絞って、画面上で実際にできる操作だけを並べる
// The three verbs (find, use, publish), listing only actions that exist in the product
type ValueItem = {
  title: string;
  description: string;
  points: string[];
};

const VALUE_ITEMS_JA: ValueItem[] = [
  {
    title: "探す",
    description:
      "公開プロンプトの一覧を、3つの軸で絞り込めます。目的が決まっていればキーワード検索も使えます。",
    points: [
      "カテゴリで絞る（文章作成・開発・調査・翻訳ほか11種）",
      "形式で絞る（プロンプト／SKILL）",
      "生成対象で絞る（テキスト／画像）",
      "タイトルや本文のキーワードで検索する"
    ]
  },
  {
    title: "使う",
    description:
      "詳細を開くと本文と入力例・出力例をそのまま読めます。使うと決めたら、チャットへ持っていくのは1操作です。",
    points: [
      "「チャットで使う」でタスクとして取り込む",
      "本文をコピーして、ほかのAIツールで使う",
      "リンクをコピーして、チームや外部に共有する",
      "いいねした投稿・保存した投稿は管理画面で一覧できる"
    ]
  },
  {
    title: "出す",
    description:
      "自分の手元でうまくいったプロンプトを公開します。投稿後も内容はいつでも直せます。",
    points: [
      "プロンプト本文、またはSKILL定義（Markdown）を投稿する",
      "入力例・出力例・想定しているAIモデルを添える",
      "参考画像やSKILLの補助ファイルを一緒に載せる",
      "投稿した内容は管理画面から編集・削除できる"
    ]
  }
];

const VALUE_ITEMS_EN: ValueItem[] = [
  {
    title: "Find",
    description:
      "Narrow the public prompt feed along three axes, or search by keyword when you already know what you need.",
    points: [
      "Filter by category (writing, coding, research, translation, and 7 more)",
      "Filter by format (prompt or SKILL)",
      "Filter by output type (text or image)",
      "Search titles and bodies by keyword"
    ]
  },
  {
    title: "Use",
    description:
      "Open a prompt to read the full body along with its input and output examples. Taking it to chat is a single action.",
    points: [
      "“Use in chat” loads the prompt as a task",
      "Copy the body to use it in another AI tool",
      "Copy the link to share it with your team or externally",
      "Liked and saved prompts are listed on your management page"
    ]
  },
  {
    title: "Publish",
    description: "Publish the prompts that worked for you. You can revise a post at any time after publishing.",
    points: [
      "Post a prompt body or a SKILL definition written in Markdown",
      "Attach input examples, output examples, and the model you had in mind",
      "Include a reference image, or supporting files for a SKILL",
      "Edit or delete your posts from the management page"
    ]
  }
];

export function PromptShareLpValue() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? VALUE_ITEMS_EN : VALUE_ITEMS_JA;
  return (
    <section id="value" className="lp-section pslp-value" aria-labelledby="pslp-value-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT YOU CAN DO" : "できること"}</p>
        <h2 id="pslp-value-heading" className="lp-heading">
          {isEn ? (
            <>Find it, use it, publish it.</>
          ) : (
            <>
              探して、使って、
              <br className="lp-br-sp" />
              出す。それだけです。
            </>
          )}
        </h2>
        <div className="pslp-value__grid">
          {items.map((item) => (
            <article key={item.title} className="pslp-value__item">
              <h3 className="pslp-value__title">{item.title}</h3>
              <p className="pslp-value__description">{item.description}</p>
              <ul className="pslp-value__points">
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
