import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 実際のチャット画面の見本。上は入力画面（タスクカード・入力欄・モデル選択）、
// 下は生成UIの枠（タイトル＋Generated UIバッジ＋サンドボックスの中身）で、
// どちらも画面に出ている文言だけを文字とCSSで並べる。装飾なので支援技術からは隠す。
// Mock of the real chat screen: the setup view on top (task cards, composer, model select)
// and a generated UI frame below (title, Generated UI badge, sandboxed body). Both reuse the
// product's own wording, drawn with text and CSS only. Decorative, so hidden from assistive tech.
function ChatLpScreenMock() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <div className="cslp-mock" aria-hidden="true">
      <div className="cslp-mock__card">
        <p className="cslp-mock__label">{isEn ? "Click a task" : "タスクをクリック"}</p>
        <div className="cslp-mock__tasks">
          {/* 実際のタスク名は絵文字付きだが、絵文字は環境によって字形が崩れるため
              同じ意味のアイコンフォントに置き換える
              The real task names carry emoji; the icon font is substituted because emoji
              glyphs are not available everywhere */}
          <span className="cslp-mock__task">
            <i className="bi bi-file-text"></i> {isEn ? "Summarize" : "要約"}
          </span>
          <span className="cslp-mock__task">
            <i className="bi bi-envelope"></i> {isEn ? "Write an email" : "メール作成"}
          </span>
          <span className="cslp-mock__task">
            <i className="bi bi-airplane"></i> {isEn ? "Plan a trip" : "旅行計画"}
          </span>
          <span className="cslp-mock__task cslp-mock__task--add">
            <i className="bi bi-plus-lg"></i>
          </span>
        </div>
        <div className="cslp-mock__composer">
          <span className="cslp-mock__composer-text">
            {isEn ? "Show me the three-day budget as a chart" : "3日間の予算配分をグラフで見せて"}
          </span>
          <span className="cslp-mock__composer-actions">
            <i className="bi bi-paperclip"></i>
            <i className="bi bi-send cslp-mock__send"></i>
          </span>
        </div>
        <p className="cslp-mock__model">
          <span className="cslp-mock__model-label">{isEn ? "AI model" : "AIモデル選択"}</span>
          <span className="cslp-mock__model-value">
            GPT-OSS 120B{isEn ? " (fast responses)" : "（高速応答）"}
            <i className="bi bi-chevron-down"></i>
          </span>
        </p>
      </div>

      <div className="cslp-mock__card cslp-mock__card--artifact">
        <div className="cslp-mock__artifact-head">
          <span className="cslp-mock__artifact-title">
            {isEn ? "Three-day budget" : "3日間の予算配分"}
          </span>
          <span className="cslp-mock__badge">
            <span className="cslp-mock__badge-dot"></span>Generated UI
          </span>
        </div>
        <div className="cslp-mock__frame">
          <span className="cslp-mock__bar cslp-mock__bar--1"></span>
          <span className="cslp-mock__bar cslp-mock__bar--2"></span>
          <span className="cslp-mock__bar cslp-mock__bar--3"></span>
          <span className="cslp-mock__bar cslp-mock__bar--4"></span>
          <span className="cslp-mock__bar cslp-mock__bar--5"></span>
        </div>
        <p className="cslp-mock__note">
          <i className="bi bi-shield-check"></i>
          {isEn
            ? "Runs inside a sandbox: no network, no storage"
            : "サンドボックスの中だけで動きます（通信なし・保存なし）"}
        </p>
      </div>
    </div>
  );
}

// ヒーローセクション（何が返ってくるかを一文で示し、実際の画面の見本を並べる）
// Hero section: one sentence on what comes back, next to a mock of the real screen
export function ChatLpHero() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="cslp-hero" aria-labelledby="cslp-hero-heading">
      <div className="lp-container cslp-hero__inner">
        <div className="cslp-hero__copy">
          <p className="lp-eyebrow">{isEn ? "CHATCORE-AI / AI CHAT" : "ChatCore-AI ／ AIチャット"}</p>
          <h1 id="cslp-hero-heading" className="cslp-hero__title">
            {isEn ? (
              <>Repeated instructions become buttons. Answers can be things you operate.</>
            ) : (
              <>
                {/* 和文は文節で折り返す位置を固定し、単語の途中で切れないようにする
                    Japanese pins the wrap point so the headline never breaks mid-phrase */}
                毎回の指示は、ボタンに。
                <br />
                答えは、動くUIで返る。
              </>
            )}
          </h1>
          <p className="cslp-hero__lead">
            {isEn
              ? "ChatCore-AI keeps the instructions you send again and again as task cards you launch with one press. Ask for a chart, a diagram, or a 3D model and the answer comes back as a working UI rendered inside a sandbox instead of a wall of text. You can try it without signing in."
              : "ChatCore-AIのAIチャットは、何度も送る指示を「タスク」カードとして残し、押すだけで呼び出せます。「グラフで」「図で」「3Dで」と頼んだときは、説明文の代わりに、その場で動くUIをサンドボックスの中に描いて返します。ログインしないままでも試せます。"}
          </p>
          <div className="cslp-hero__cta">
            <Link href="/" className="lp-btn lp-btn--primary lp-btn--large">
              {isEn ? "Open the chat" : "チャットを開く"}
            </Link>
            <Link href="/chat/lp#value" className="lp-btn lp-btn--ghost lp-btn--large">
              {isEn ? "See what it does" : "できることを見る"}
            </Link>
          </div>
          <ul className="lp-hero__trust">
            <li>{isEn ? "Works without an account" : "登録なしで試せる"}</li>
            <li>{isEn ? "Four models to switch between" : "モデルは4種類から選べる"}</li>
            <li>{isEn ? "14 task cards from the start" : "タスクは最初から14種類"}</li>
          </ul>
        </div>
        <ChatLpScreenMock />
      </div>
    </section>
  );
}
