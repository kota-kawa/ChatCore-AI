import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 投稿カードの見本。実際のカードと同じ情報の並び（タグ→タイトル→本文→操作）を文字だけで再現する。
// 数値は捏造せず、押せる操作の名前だけを示す。装飾なので支援技術からは隠す。
// Sample prompt card mirroring the real card's information order (tags, title, body, actions)
// using text only. No invented metrics: it shows the action names, nothing more. Decorative,
// so it is hidden from assistive technology.
function PromptShareLpCardMock() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <div className="pslp-cardmock" aria-hidden="true">
      <article className="pslp-cardmock__card">
        <div className="pslp-cardmock__tags">
          <span className="pslp-cardmock__tag pslp-cardmock__tag--format">
            {isEn ? "Prompt" : "プロンプト"}
          </span>
          <span className="pslp-cardmock__tag">{isEn ? "Text" : "テキスト"}</span>
          <span className="pslp-cardmock__tag">{isEn ? "Writing" : "文章作成"}</span>
        </div>
        <h3 className="pslp-cardmock__title">
          {isEn ? "Rewrite meeting notes into a shareable summary" : "議事録を、共有できる要約に書き直す"}
        </h3>
        <p className="pslp-cardmock__body">
          {isEn
            ? "You are an editor. Rewrite the notes below into:\n1. Decisions (max 3 lines)\n2. Open questions and owners\n3. Next actions with due dates"
            : "あなたは編集者です。以下の議事録を次の形式に書き直してください。\n1. 決まったこと（3行以内）\n2. 未決事項と担当\n3. 次のアクションと期限"}
        </p>
        <div className="pslp-cardmock__meta">
          <span>
            <i className="bi bi-heart"></i> {isEn ? "Like" : "いいね"}
          </span>
          <span>
            <i className="bi bi-chat"></i> {isEn ? "Comment" : "コメント"}
          </span>
          <span className="pslp-cardmock__use">
            <i className="bi bi-plus-circle"></i> {isEn ? "Use in chat" : "チャットで使う"}
          </span>
        </div>
      </article>
      <article className="pslp-cardmock__card pslp-cardmock__card--secondary">
        <div className="pslp-cardmock__tags">
          <span className="pslp-cardmock__tag pslp-cardmock__tag--format">SKILL</span>
          <span className="pslp-cardmock__tag">{isEn ? "Text" : "テキスト"}</span>
          <span className="pslp-cardmock__tag">{isEn ? "Coding" : "開発・プログラミング"}</span>
        </div>
        <h3 className="pslp-cardmock__title">
          {isEn ? "Review a pull request against a checklist" : "チェックリストに沿ってPRをレビューする"}
        </h3>
        <p className="pslp-cardmock__body">
          {isEn ? "# Purpose\n## Steps\n1. ..." : "# 目的\n## 手順\n1. ..."}
        </p>
      </article>
    </div>
  );
}

// ヒーローセクション（誰が何をできるかを一文で示し、実際のカードの見本を並べる）
// Hero section: one sentence on who does what, next to a sample of the real card
export function PromptShareLpHero() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="pslp-hero">
      <div className="lp-container pslp-hero__inner">
        <div className="pslp-hero__copy">
          <p className="lp-eyebrow">{isEn ? "CHATCORE-AI / PROMPT LIBRARY" : "ChatCore-AI ／ プロンプト共有"}</p>
          <h1 className="pslp-hero__title">
            {isEn ? (
              <>Find a prompt that already works, and use it as is.</>
            ) : (
              <>
                {/* 和文は文節で折り返す位置を固定し、単語の途中で切れないようにする
                    Japanese pins the wrap point so the headline never breaks mid-phrase */}
                うまくいったプロンプトを、
                <br />
                探して、そのまま使う。
              </>
            )}
          </h1>
          <p className="pslp-hero__lead">
            {isEn
              ? "Browse prompts and SKILLs that other people actually use, plus image-generation posts with AI-generated examples. Filter by category, format, and output type. Press “Use in chat” and a prompt is loaded into ChatCore-AI as a ready-to-run task. Reading requires no account."
              : "ほかの人が実際に使っているプロンプトやSKILL、AI画像生成で作成された作例画像付きの投稿を、カテゴリ・形式・生成対象で絞り込んで探せます。気に入ったプロンプトは「チャットで使う」を押すだけで、ChatCore-AIのチャットにタスクとして読み込まれます。閲覧にアカウントは必要ありません。"}
          </p>
          <div className="pslp-hero__cta">
            <Link href="/prompt_share" className="lp-btn lp-btn--primary lp-btn--large">
              {isEn ? "Browse public prompts" : "公開プロンプトを探す"}
            </Link>
            <Link href="/register" className="lp-btn lp-btn--ghost lp-btn--large">
              {isEn ? "Sign up and post" : "登録して投稿する"}
            </Link>
          </div>
          <ul className="lp-hero__trust">
            <li>{isEn ? "No account needed to read" : "閲覧はログイン不要"}</li>
            <li>{isEn ? "Posting and saving are free" : "投稿・保存も無料"}</li>
            <li>{isEn ? "11 categories, filterable" : "カテゴリ11種で絞り込み"}</li>
          </ul>
        </div>
        <PromptShareLpCardMock />
      </div>
    </section>
  );
}
