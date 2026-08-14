import { useTranslation } from "../../contexts/locale_context";

// AIチャットページのFAQ。JSON-LDと表示の両方でこのデータを使う
// FAQ for the AI chat page; this data feeds both JSON-LD and the visible UI
export const CHAT_LP_FAQ_ITEMS = [
  {
    question: "アカウントがなくても使えますか？",
    answer:
      "使えます。ログインしないままメッセージを送り、最初から入っているタスクカードや生成UIも試せます。ただし1日に送れる回数に上限があり（初期設定は10回）、会話は履歴に残りません。履歴の保存、タスクの作成・編集、メモ保存、共有リンクの作成には無料アカウントが必要です。"
  },
  {
    question: "タスクボタンは何をしていますか？",
    answer:
      "カードを押すと「【タスク】要約」のような形でメッセージが送られ、入力欄に書いた内容が「【状況・作業環境】」として一緒に渡ります。裏側ではタスクに登録されたプロンプトテンプレート・回答ルール・出力テンプレート・入出力例がAIに渡っていて、その内容は送信後に「プロンプト」を開けばそのまま読めます。"
  },
  {
    question: "生成UIはいつ出ますか？勝手に出ることはありますか？",
    answer:
      "「グラフで」「図解して」「インタラクティブなデモを」のように、目に見える形を明示して頼んだときだけ出ます。比較・手順・計算・コード例は通常どおり文章で返ります。「テキストだけ」「図は不要」と書けば、頼まない限りUIは出ません。"
  },
  {
    question: "3Dでは何ができて、何ができませんか？",
    answer:
      "「3Dで」「立体で」「Three.jsで」と頼むと、シーン・カメラ・光源・形をひとそろい作ったThree.jsの画面が返り、ドラッグで視点を回せます。使えるライブラリはThree.jsだけで、外部CDNからの読み込み、URL指定のテクスチャや3Dモデルの読み込みはできません。表示できる高さは160〜900pxです。"
  },
  {
    question: "会話は他の人に見えますか？",
    answer:
      "自分で共有リンクを作らないかぎり、他の人には見えません。共有リンクを作った場合は、URLを知っている人なら誰でもその会話を閲覧でき、「このチャットを続ける」で自分のコピーから続きを話せます。未保存チャットモードの会話は履歴に残らず、共有リンクも作れません。"
  }
] as const;

export const CHAT_LP_FAQ_ITEMS_EN = [
  {
    question: "Can I use it without an account?",
    answer:
      "Yes. You can send messages, use the preloaded task cards, and see generated UIs without signing in. The number of messages per day is capped (10 by default) and nothing is kept in history. Keeping history, creating or editing tasks, saving memos, and creating share links need a free account."
  },
  {
    question: "What does a task button actually do?",
    answer:
      "Pressing a card sends a message shaped like “【タスク】Summarize”, carrying whatever you typed in the box as the situation section. Behind it, the task's prompt template, response rules, output template, and input and output examples go to the model, and you can read all of them under the “Prompt” disclosure after sending."
  },
  {
    question: "When does a generated UI appear? Can it appear uninvited?",
    answer:
      "Only when you explicitly ask for something visible, such as a chart, a diagram, or an interactive demo. Comparisons, procedures, calculations, and code examples come back as text as usual, and writing “text only” or “no diagram” keeps it that way."
  },
  {
    question: "What can 3D do, and what can it not do?",
    answer:
      "Asking for 3D, a solid shape, or Three.js returns a Three.js screen with a scene, camera, light, and geometry that you can drag to orbit. Three.js is the only library available: no external CDNs, and no textures or 3D models loaded from a URL. The frame is between 160 and 900 pixels tall."
  },
  {
    question: "Can other people see my conversations?",
    answer:
      "Not unless you create a share link yourself. Once you do, anyone with the URL can read that conversation and press “Continue this chat” to keep going in their own copy. Temporary chats are never stored and cannot be shared at all."
  }
] as const;

export function ChatLpFaq() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const items = isEn ? CHAT_LP_FAQ_ITEMS_EN : CHAT_LP_FAQ_ITEMS;
  return (
    <section id="faq" className="lp-section lp-faq" aria-labelledby="cslp-faq-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "FREQUENTLY ASKED QUESTIONS" : "よくある質問"}</p>
        <h2 id="cslp-faq-heading" className="lp-heading">
          {isEn ? (
            <>Questions people ask before the first message.</>
          ) : (
            <>
              最初の1通を送る前に、
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
