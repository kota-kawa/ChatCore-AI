import { MODEL_OPTIONS } from "../../lib/chat_page/constants";
import { formatModelOptionLabel } from "../../lib/chat_page/model_label";
import { useTranslation } from "../../contexts/locale_context";

// 何ができるかと同じ強さで、できないことも先に見せるセクション。
// モデル一覧はチャット画面と同じ定数から引くので、実際の選択肢と必ず一致する。
// Section that states the limits as plainly as the capabilities.
// The model list comes from the same constant as the chat screen, so it always matches the real UI.
const LIMITS_JA = [
  "生成UIは表示専用です。サンドボックス化したiframeの中で動き、外部との通信・データの保存・元のページへのアクセスはできません。画像やフォントも埋め込みだけです。",
  "3Dで使えるライブラリはThree.jsだけで、ChatCore-AI自身が配信しているものを読み込みます。外部CDNのライブラリは使えません。",
  "生成UIは頼まれたときだけ出ます。比較・手順・計算・コード例は、通常どおり文章で返ります。",
  "Web検索をするかどうかはAIが判断します。必ず検索させる手動スイッチはありません。",
  "添付できるのは文書とコードです（一度に5件まで、1件1MBまで）。画像は添付できません。",
  "未ログインのままでも送れますが、1日に送れる回数に上限があり（初期設定は10回）、会話は履歴に残りません。",
  "未保存チャットは履歴に残らず、共有リンクも作れません。作成した共有リンクは、URLを知っている人なら誰でも開けます。"
];

const LIMITS_EN = [
  "A generated UI is display-only. It runs inside a sandboxed iframe with no network access, no storage, and no access to the page around it; images and fonts must be embedded.",
  "Three.js is the only library available for 3D, and it is served by ChatCore-AI itself. Libraries from external CDNs cannot be loaded.",
  "A generated UI appears only when you ask for one. Comparisons, procedures, calculations, and code examples come back as text as usual.",
  "The AI decides whether to run a web search. There is no manual switch that forces one.",
  "Attachments are documents and code (up to five files at a time, 1MB each). Images cannot be attached.",
  "You can send messages without signing in, but the number of messages per day is capped (10 by default) and the conversation is not kept in history.",
  "A temporary chat is never stored and cannot be shared. A share link you do create can be opened by anyone who knows the URL."
];

type ScopeItem = { label: string; note: string };

const OUTPUT_MODES_JA: ScopeItem[] = [
  {
    label: "テキスト（既定）",
    note: "説明・比較・手順・計算・コードは、文章とMarkdownで返ります。"
  },
  {
    label: "2D",
    note: "「可視化」「図解」「グラフ」「フローチャート」「インタラクティブなデモ」と頼んだときに、その場で触れるUIになります。"
  },
  {
    label: "3D",
    note: "「3D」「立体」「Three.js」「回転」などを頼んだときに、Three.jsのシーンとして描かれます。"
  }
];

const OUTPUT_MODES_EN: ScopeItem[] = [
  { label: "Text (default)", note: "Explanations, comparisons, procedures, calculations, and code come back as prose and Markdown." },
  {
    label: "2D",
    note: "Asking for a visualization, diagram, chart, flow, timeline, or interactive demo produces a UI you can use in place."
  },
  {
    label: "3D",
    note: "Asking for 3D, a solid shape, Three.js, or rotation produces a Three.js scene."
  }
];

const INPUTS_JA: ScopeItem[] = [
  { label: "入力欄の文章", note: "1回あたり30,000文字まで送れます。" },
  {
    label: "ファイル",
    note: "PDF・Word・Excel・PowerPoint・テキスト・コードを、一度に5件まで（1件1MBまで）添付できます。"
  },
  {
    label: "参照の切り替え",
    note: "追加メニューから「メモ・マイコンテキストを参照」「共有プロンプトを参照」をオンにできます（メモの参照はログイン時）。"
  }
];

const INPUTS_EN: ScopeItem[] = [
  { label: "The message box", note: "Up to 30,000 characters per message." },
  {
    label: "Files",
    note: "Attach PDF, Word, Excel, PowerPoint, text, and code files: five at a time, 1MB each."
  },
  {
    label: "Lookup toggles",
    note: "The add menu turns on lookups against your memos and personal context, or against shared prompts (memos require signing in)."
  }
];

export function ChatLpScope() {
  const { locale, t } = useTranslation();
  const isEn = locale === "en";
  const limits = isEn ? LIMITS_EN : LIMITS_JA;
  const outputModes = isEn ? OUTPUT_MODES_EN : OUTPUT_MODES_JA;
  const inputs = isEn ? INPUTS_EN : INPUTS_JA;
  return (
    <section id="scope" className="lp-section cslp-scope" aria-labelledby="cslp-scope-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT IT COVERS" : "対応範囲・仕組み"}</p>
        <h2 id="cslp-scope-heading" className="lp-heading">
          {isEn ? (
            <>How you ask decides what comes back.</>
          ) : (
            <>
              返ってくる形は、
              <br className="lp-br-sp" />
              頼み方で決まります。
            </>
          )}
        </h2>

        <div className="cslp-scope__axes">
          <div className="cslp-axis">
            <p className="cslp-axis__name">{isEn ? "SHAPE OF THE ANSWER" : "答えの形"}</p>
            <ul className="cslp-axis__list">
              {outputModes.map((mode) => (
                <li key={mode.label} className="cslp-axis__item">
                  <span className="cslp-axis__label">{mode.label}</span>
                  <span className="cslp-axis__note">{mode.note}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="cslp-axis">
            <p className="cslp-axis__name">{isEn ? "WHAT YOU CAN SEND" : "一緒に渡せるもの"}</p>
            <ul className="cslp-axis__list">
              {inputs.map((input) => (
                <li key={input.label} className="cslp-axis__item">
                  <span className="cslp-axis__label">{input.label}</span>
                  <span className="cslp-axis__note">{input.note}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <h3 className="cslp-scope__subtitle">{isEn ? "Models you can switch between" : "切り替えられるAIモデル"}</h3>
        <ul className="cslp-chips">
          {MODEL_OPTIONS.map((option) => (
            <li key={option.value}>{formatModelOptionLabel(option, t, locale)}</li>
          ))}
        </ul>

        <h3 className="cslp-scope__subtitle">{isEn ? "Before you start, know this" : "使う前に知っておくこと"}</h3>
        <ul className="cslp-limits">
          {limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
