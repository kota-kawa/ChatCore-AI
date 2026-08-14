import { useTranslation } from "../../contexts/locale_context";
import {
  getCategoryLabel,
  PROMPT_CATEGORY_KEYS
} from "../../scripts/prompt_share/prompt_category_registry";

// 扱える範囲と、扱えない範囲の両方を先に見せるセクション。
// カテゴリはレジストリから引くので、実際の絞り込みUIと必ず一致する。
// Section that states up front both what the service covers and what it does not.
// Categories come from the registry so this list always matches the real filter UI.
const LIMITS_JA = [
  "投稿はすべて公開です。非公開のまま下書きを溜める機能はありません。",
  "生成対象はテキストと画像の2種類です。動画・音声向けの投稿区分は現時点でありません。",
  "添付できるのは参考画像（PNG・JPEG・WebP・GIF、1件5MBまで）です。",
  "「チャットで使う」で読み込んだプロンプトは、ChatCore-AIのチャットで実行します。ほかのAIツールで使う場合は本文をコピーしてください。"
];

const LIMITS_EN = [
  "Every post is public. There is no private draft area.",
  "Output types are text and image. There is no video or audio category yet.",
  "The only attachment is a reference image (PNG, JPEG, WebP, or GIF, up to 5MB each).",
  "“Use in chat” runs the prompt inside ChatCore-AI. To use it elsewhere, copy the body instead."
];

export function PromptShareLpScope() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const limits = isEn ? LIMITS_EN : LIMITS_JA;
  return (
    <section id="scope" className="lp-section pslp-scope" aria-labelledby="pslp-scope-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT IT COVERS" : "対応範囲"}</p>
        <h2 id="pslp-scope-heading" className="lp-heading">
          {isEn ? (
            <>Two axes decide where a post lands.</>
          ) : (
            <>
              投稿の置き場所は、
              <br className="lp-br-sp" />
              2つの軸で決まります。
            </>
          )}
        </h2>

        <div className="pslp-scope__axes">
          <div className="pslp-axis">
            <p className="pslp-axis__name">{isEn ? "FORMAT" : "形式"}</p>
            <ul className="pslp-axis__list">
              <li className="pslp-axis__item">
                <span className="pslp-axis__label">{isEn ? "Prompt" : "プロンプト"}</span>
                <span className="pslp-axis__note">
                  {isEn
                    ? "A single instruction you paste into a chat. The body is required; input and output examples are optional."
                    : "そのまま貼って使える指示文。本文が必須で、入力例・出力例は任意です。"}
                </span>
              </li>
              <li className="pslp-axis__item">
                <span className="pslp-axis__label">SKILL</span>
                <span className="pslp-axis__note">
                  {isEn
                    ? "A packaged procedure written in Markdown: purpose, steps, and rules, plus optional supporting files."
                    : "目的・手順・ルールをMarkdownで書いた手順パッケージ。補助ファイルも添えられます。"}
                </span>
              </li>
            </ul>
          </div>
          <div className="pslp-axis">
            <p className="pslp-axis__name">{isEn ? "OUTPUT TYPE" : "生成対象"}</p>
            <ul className="pslp-axis__list">
              <li className="pslp-axis__item">
                <span className="pslp-axis__label">{isEn ? "Text" : "テキスト"}</span>
                <span className="pslp-axis__note">
                  {isEn
                    ? "Prompts whose result is text: writing, summaries, code, translation, analysis."
                    : "文章・要約・コード・翻訳・分析など、結果が文章になるプロンプト。"}
                </span>
              </li>
              <li className="pslp-axis__item">
                <span className="pslp-axis__label">{isEn ? "Image" : "画像"}</span>
                <span className="pslp-axis__note">
                  {isEn
                    ? "Prompts for image generation. You can attach a reference image so readers see what the prompt produces."
                    : "画像生成向けのプロンプト。仕上がりが伝わるように参考画像を添付できます。"}
                </span>
              </li>
            </ul>
          </div>
        </div>

        <h3 className="pslp-scope__categories-title">
          {isEn ? "Categories (what you ask the AI to do)" : "カテゴリ（AIに何をさせるか）"}
        </h3>
        <ul className="pslp-chips">
          {PROMPT_CATEGORY_KEYS.map((key) => (
            <li key={key}>{getCategoryLabel(key, locale)}</li>
          ))}
        </ul>

        <h3 className="pslp-scope__limits-title">
          {isEn ? "Before you post, know this" : "投稿する前に知っておくこと"}
        </h3>
        <ul className="pslp-limits">
          {limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
