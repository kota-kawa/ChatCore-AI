import { useTranslation } from "../../contexts/locale_context";

// 「タスクボタン・生成UI・会話まわりの操作」の3つに絞り、画面上で実際にできる操作だけを並べる
// Three groups (task buttons, generated UI, conversation tools) listing only actions that exist
type ValueItem = {
  icon: string;
  title: string;
  description: string;
  points: string[];
};

const VALUE_ITEMS_JA: ValueItem[] = [
  {
    icon: "bi-grid-1x2",
    title: "タスクボタン",
    description:
      "よく使う指示を、押すだけで呼び出せるカードとして残せます。最初から14種類が入っていて、ログインすれば自分用に足したり直したりできます。",
    points: [
      "カードを押すと「【タスク】要約」の形で送られ、入力欄に書いた内容は「【状況・作業環境】」として一緒に渡ります",
      "タスクの中身（プロンプトテンプレート・回答ルール・出力テンプレート・入出力例）は、送信後に「プロンプト」を開けばそのまま読めます",
      "＋ボタンで新規作成。タイトルと内容を書くほか、AI補助で下書きを作ることもできます",
      "鉛筆で編集、ゴミ箱で削除、カードを長押しすると掴んで並び替えできます（ログイン時）",
      "プロンプト共有で「チャットで使う」を押すと、公開プロンプトがそのままタスクとして並びます"
    ]
  },
  {
    icon: "bi-stars",
    title: "生成UI・3D",
    description:
      "「グラフで」「図解して」と頼んだときだけ、文章の代わりに動くUIが返ります。「3Dで」と書いた場合はThree.jsの立体を描きます。",
    points: [
      "2Dはチャート・表・タイムライン・小さなデモなど、その場で触れるUIとして描かれます",
      "3Dはシーン・カメラ・光源・形をひとそろい作り、ドラッグで視点を回せます",
      "表示は1メッセージあたり最大3つ、高さ160〜900pxの枠の中に収まります",
      "組み上がりが不十分だったときは、1回だけ自動で作り直してから返します",
      "「テキストだけ」「図は不要」と書けば、UIは出さずに文章で答えます"
    ]
  },
  {
    icon: "bi-chat-left-text",
    title: "会話まわりの操作",
    description: "返ってきた答えを、その場で残す・渡す・やり直すための操作がそろっています。",
    points: [
      "AIモデルは4種類（高速応答・バランス型・深い思考・丁寧な文章）から切り替えられます",
      "最新の情報が要るとAIが判断したときだけWeb検索し、本文に出典チップを付けます",
      "回答は「メモに保存」「回答をコピー」で残せます。メール文などはコピー用の枠に入って返ります",
      "「チャットを共有」でリンクを発行。受け取った人は「このチャットを続ける」で自分のコピーから続けられます",
      "メッセージを編集したり回答を再生成するとバージョンが増え、‹ 1/2 › で行き来できます",
      "未保存チャットモードは履歴に残しません。プロジェクトにまとめれば、カスタム指示を全チャットに効かせられます"
    ]
  }
];

const VALUE_ITEMS_EN: ValueItem[] = [
  {
    icon: "bi-grid-1x2",
    title: "Task buttons",
    description:
      "Keep the instructions you send often as cards you launch with one press. Fourteen come preloaded, and once you sign in you can add and rewrite your own.",
    points: [
      "Pressing a card sends it as “【タスク】Summarize”, and whatever you typed in the box travels with it as the situation section",
      "The task body (prompt template, response rules, output template, input and output examples) stays readable under the “Prompt” disclosure after sending",
      "The + button creates a new task: write the title and body yourself, or let AI assistance draft it",
      "Pencil to edit, trash to delete, and hold a card to pick it up and reorder it (signed in)",
      "Pressing “Use in chat” on a shared prompt drops that public prompt straight into your task list"
    ]
  },
  {
    icon: "bi-stars",
    title: "Generated UI and 3D",
    description:
      "Only when you ask for a chart or a diagram does the answer come back as a working UI. Ask for 3D and it builds a Three.js scene instead.",
    points: [
      "2D results are charts, tables, timelines, and small demos you can interact with in place",
      "3D results build a scene, camera, light, and geometry, and you can drag to orbit the view",
      "At most three UIs per message, each in a frame between 160 and 900 pixels tall",
      "If the result comes back incomplete, one automatic repair pass runs before you see it",
      "Write “text only” or “no diagram” and it answers in prose instead"
    ]
  },
  {
    icon: "bi-chat-left-text",
    title: "Around the conversation",
    description: "The controls for keeping, passing on, and redoing an answer are all in the same place.",
    points: [
      "Switch between four models: fast, balanced, deep thinking, and careful writing",
      "Web search runs only when the AI judges that fresh information is needed, and sources appear as chips in the answer",
      "Save an answer as a memo or copy it; deliverables such as an email body come back in their own copy block",
      "“Share chat” issues a link, and the person who opens it can press “Continue this chat” to keep going in their own copy",
      "Editing a message or regenerating an answer adds a version you can move through with ‹ 1/2 ›",
      "Temporary chat keeps nothing in history, and a project applies its custom instructions to every chat inside it"
    ]
  }
];

export function ChatLpValue() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? VALUE_ITEMS_EN : VALUE_ITEMS_JA;
  return (
    <section id="value" className="lp-section cslp-value" aria-labelledby="cslp-value-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT YOU CAN DO" : "できること"}</p>
        <h2 id="cslp-value-heading" className="lp-heading">
          {isEn ? (
            <>Launch it, render it, keep it.</>
          ) : (
            <>
              押して呼び出し、
              <br className="lp-br-sp" />
              描かせて、残す。
            </>
          )}
        </h2>
        <div className="cslp-value__grid">
          {items.map((item) => (
            <article key={item.title} className="cslp-value__item">
              <span className="cslp-value__icon" aria-hidden="true">
                <i className={`bi ${item.icon}`}></i>
              </span>
              <h3 className="cslp-value__title">{item.title}</h3>
              <p className="cslp-value__description">{item.description}</p>
              <ul className="cslp-value__points">
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
