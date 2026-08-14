import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// メモ画面の見本。実際の画面と同じ情報の並び（一覧のカード → 詳細の編集タブ・自動保存）を
// 文字とCSSだけで再現する。件数などの数値は作らず、実在する操作名だけを置く。装飾なので
// 支援技術からは隠す。
// Sample of the memo screen, mirroring the real information order (list card, then the detail
// view's edit tabs and autosave status) using text and CSS only. No invented numbers: it shows
// action names that exist in the product. Decorative, so it is hidden from assistive technology.
function MemoLpScreenMock() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <div className="mslp-mock" aria-hidden="true">
      <div className="mslp-mock__window">
        <div className="mslp-mock__titlebar">
          <span className="mslp-mock__dot"></span>
          <span className="mslp-mock__dot"></span>
          <span className="mslp-mock__dot"></span>
          <span className="mslp-mock__titletext">ChatCore Memo</span>
        </div>
        <div className="mslp-mock__body">
          <div className="mslp-mock__search">
            <i className="bi bi-search"></i>
            <span>{isEn ? "Search memos" : "メモを検索"}</span>
          </div>
          <article className="mslp-mock__card">
            <div className="mslp-mock__card-head">
              <span className="mslp-mock__pin">
                <i className="bi bi-pin-angle-fill"></i>
              </span>
              <h3 className="mslp-mock__card-title">
                {isEn ? "PostgreSQL index design, summarized" : "PostgreSQLのインデックス設計まとめ"}
              </h3>
            </div>
            <p className="mslp-mock__card-body">
              {isEn
                ? "## Rules of thumb\n- Composite index: put the equality column first\n- Partial index for the rows you actually query"
                : "## 判断の目安\n- 複合インデックスは等値条件の列を先頭に\n- 実際に絞る行だけなら部分インデックス"}
            </p>
            <div className="mslp-mock__card-meta">
              <span className="mslp-mock__collection">
                <span className="mslp-mock__collection-dot"></span>
                {isEn ? "Work notes" : "仕事メモ"}
              </span>
              <span>
                <i className="bi bi-clock"></i> {isEn ? "Updated today" : "今日更新"}
              </span>
            </div>
          </article>
          <div className="mslp-mock__editor">
            <div className="mslp-mock__tabs">
              <span className="mslp-mock__tab mslp-mock__tab--active">
                <i className="bi bi-code-slash"></i> {isEn ? "Edit" : "編集"}
              </span>
              <span className="mslp-mock__tab">
                <i className="bi bi-eye"></i> {isEn ? "Preview" : "プレビュー"}
              </span>
            </div>
            <span className="mslp-mock__autosave">
              <i className="bi bi-check2"></i> {isEn ? "Saved" : "保存済み"}
            </span>
          </div>
        </div>
      </div>
      <p className="mslp-mock__caption">
        {isEn
          ? "One click in a chat turns an answer into this."
          : "チャットの回答は、1クリックでこの形になります。"}
      </p>
    </div>
  );
}

// ヒーローセクション。何をどう残せるかを一文で示し、実際の画面の見本を横に並べる
// Hero section: one sentence on what gets saved and how, next to a sample of the real screen
export function MemoLpHero() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="mslp-hero">
      <div className="lp-container mslp-hero__inner">
        <div className="mslp-hero__copy">
          <p className="lp-eyebrow">{isEn ? "CHATCORE-AI / MEMO" : "ChatCore-AI ／ メモ"}</p>
          <h1 className="mslp-hero__title">
            {isEn ? (
              <>Keep the answer. Find it again later.</>
            ) : (
              <>
                {/* 和文は文節で折り返す位置を固定し、単語の途中で切れないようにする
                    Japanese pins the wrap point so the headline never breaks mid-phrase */}
                AIの回答を、そのまま
                <br />
                あとで探せるメモに。
              </>
            )}
          </h1>
          <p className="mslp-hero__lead">
            {isEn
              ? "Press the bookmark button under a chat answer and it becomes a memo. The body is Markdown you can rewrite, and it autosaves while you type. Search by keyword, group memos into collections, pin them, archive them. A memo is yours alone until you create a share link for it."
              : "チャットの回答の下にあるブックマークのボタンを押すと、その回答がそのままメモになります。本文はMarkdownのまま書き直せて、入力が止まると自動で保存されます。キーワード検索、コレクション分け、ピン留め、アーカイブで整理できます。メモは共有リンクを作るまで、自分だけのものです。"}
          </p>
          <div className="mslp-hero__cta">
            <Link href="/memo" className="lp-btn lp-btn--primary lp-btn--large">
              {isEn ? "Open memos" : "メモを開く"}
            </Link>
            <Link href="/lp" className="lp-btn lp-btn--ghost lp-btn--large">
              {isEn ? "About ChatCore-AI" : "ChatCore-AIとは"}
            </Link>
          </div>
          <ul className="lp-hero__trust">
            <li>{isEn ? "Saved in one click from a chat" : "チャットから1クリックで保存"}</li>
            <li>{isEn ? "Markdown body, autosaved" : "本文はMarkdown・自動保存"}</li>
            <li>{isEn ? "Private until you share it" : "共有するまで自分だけ"}</li>
          </ul>
        </div>
        <MemoLpScreenMock />
      </div>
    </section>
  );
}
