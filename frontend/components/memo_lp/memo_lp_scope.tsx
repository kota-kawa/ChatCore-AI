import { useTranslation } from "../../contexts/locale_context";

// 対応範囲と前提。できることより先に、非公開の範囲・共有リンクが見せるもの・できないことを出す。
// 記載はすべて blueprints/memo と frontend/components/memo の実装に対応させている。
// Scope and prerequisites. What stays private, what a share link exposes, and what is missing
// come before the sales pitch. Every statement maps to blueprints/memo and frontend/components/memo.
type ScopeItem = { label: string; note: string };

// 保存の入口 / Ways a memo gets created
const ENTRY_POINTS_JA: ScopeItem[] = [
  {
    label: "チャットの回答から",
    note: "回答の下のブックマークのボタン1つで保存されます。タイトルが空なら本文の1行目が使われます。"
  },
  {
    label: "メモ画面で直接",
    note: "タイトルと本文を書いて保存します。本文はMarkdownで、編集とプレビューを切り替えられます。"
  },
  {
    label: "MCP対応のAIクライアントから",
    note: "接続を許可したクライアントが create_memo・update_memo・append_memo_content でメモを作成・更新・追記できます。"
  }
];

const ENTRY_POINTS_EN: ScopeItem[] = [
  {
    label: "From a chat answer",
    note: "One press of the bookmark button under the answer. If the title is empty, the first line of the body is used."
  },
  {
    label: "Directly on the memo screen",
    note: "Write a title and a body. The body is Markdown, with edit and preview tabs."
  },
  {
    label: "From an MCP-capable AI client",
    note: "A client you have authorized can create, replace, or append to memos via create_memo, update_memo, and append_memo_content."
  }
];

// 整理の単位 / The units of organisation
const ORGANIZERS_JA: ScopeItem[] = [
  {
    label: "コレクション",
    note: "名前と色を決めてメモをまとめます。1件のメモが入れるコレクションは1つです。"
  },
  {
    label: "ピン留め",
    note: "一覧の先頭に固定します。ピン留めしたメモは「ピン留め」「その他」に分かれて並びます。"
  },
  {
    label: "アーカイブ",
    note: "削除せずにふだんの一覧から外します。アーカイブだけを表示して戻すこともできます。"
  }
];

const ORGANIZERS_EN: ScopeItem[] = [
  {
    label: "Collections",
    note: "Group memos under a name and colour you choose. A memo belongs to at most one collection."
  },
  {
    label: "Pins",
    note: "Keep a memo at the top. Pinned memos are listed separately from the rest."
  },
  {
    label: "Archive",
    note: "Take a memo out of the everyday list without deleting it. You can view the archive alone and restore from it."
  }
];

// 並び順とエクスポート形式（実際の選択肢そのまま） / Sort options and export formats, exactly as offered
const SORTS_JA = ["手動順", "新しい順", "更新順", "古い順", "タイトル順", "AI類似検索"];
const SORTS_EN = ["Manual", "Newest", "Recently updated", "Oldest", "Title", "AI similarity"];

// 共有リンクの公開範囲 / What a share link does and does not expose
const PRIVACY_ROWS_JA: ScopeItem[] = [
  {
    label: "共有リンクを開いた人に見えるもの",
    note: "そのメモのタイトル、保存日時、本文だけです。ログインは要りません。"
  },
  {
    label: "見えないもの",
    note: "あなたの名前やアカウント情報、ほかのメモ、コレクション、アーカイブ。共有していないメモは一切出ません。"
  },
  {
    label: "リンクを作らないかぎり",
    note: "メモは自分のアカウントからしか開けません。ログインしていない状態では一覧も表示されません。"
  }
];

const PRIVACY_ROWS_EN: ScopeItem[] = [
  {
    label: "What a share link shows",
    note: "That memo's title, the time it was saved, and its body. No sign-in required."
  },
  {
    label: "What it does not show",
    note: "Your name or account details, your other memos, your collections, your archive. Nothing you have not shared appears."
  },
  {
    label: "Until you create a link",
    note: "A memo opens only from your own account. Signed out, the list is not shown at all."
  }
];

// 先に伝えておく制限 / Limits stated up front
const LIMITS_JA = [
  "メモの作成・閲覧には無料アカウントが必要です。ログインしていない人が見られるのは、渡された共有リンク1件だけです。",
  "メモ画面から作る共有リンクは30日で期限切れになります。期限が切れるとそのページは開けなくなります。",
  "共有を途中でやめる取り消しボタンは、まだメモ画面にありません。早く止めたいときはそのメモを削除してください（削除すると共有リンクも無効になります）。",
  "編集履歴はありません。詳細画面の編集は自動保存で上書きされ、前の版に戻すことはできません。",
  "メモに添付できるファイルや画像はありません。残せるのはテキスト（Markdown）だけです。",
  "MCP経由で書き込める本文は1件20,000文字まで、書き込みは1時間に60回までです。"
];

const LIMITS_EN = [
  "Creating and reading memos needs a free account. Someone signed out can only open a share link you handed them.",
  "A share link created from the memo screen expires after 30 days, after which the page no longer opens.",
  "There is no revoke button on the memo screen yet. To stop sharing sooner, delete the memo — deleting it also kills the link.",
  "There is no edit history. Edits in the detail view autosave over the previous text and cannot be rolled back.",
  "Memos take no file or image attachments. Text (Markdown) is all they hold.",
  "Writes over MCP are capped at 20,000 characters per body and 60 writes per hour."
];

export function MemoLpScope() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  const entryPoints = isEn ? ENTRY_POINTS_EN : ENTRY_POINTS_JA;
  const organizers = isEn ? ORGANIZERS_EN : ORGANIZERS_JA;
  const sorts = isEn ? SORTS_EN : SORTS_JA;
  const privacyRows = isEn ? PRIVACY_ROWS_EN : PRIVACY_ROWS_JA;
  const limits = isEn ? LIMITS_EN : LIMITS_JA;
  return (
    <section id="scope" className="lp-section mslp-scope" aria-labelledby="mslp-scope-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{isEn ? "WHAT IT COVERS" : "対応範囲・前提"}</p>
        <h2 id="mslp-scope-heading" className="lp-heading">
          {isEn ? (
            <>A memo is private until you hand out a link.</>
          ) : (
            <>
              メモは、リンクを渡すまで
              <br className="lp-br-sp" />
              自分だけのものです。
            </>
          )}
        </h2>

        <div className="mslp-scope__axes">
          <div className="mslp-axis">
            <p className="mslp-axis__name">{isEn ? "WHERE A MEMO COMES FROM" : "保存の入口"}</p>
            <ul className="mslp-axis__list">
              {entryPoints.map((item) => (
                <li key={item.label} className="mslp-axis__item">
                  <span className="mslp-axis__label">{item.label}</span>
                  <span className="mslp-axis__note">{item.note}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="mslp-axis">
            <p className="mslp-axis__name">{isEn ? "HOW IT IS ORGANIZED" : "整理の単位"}</p>
            <ul className="mslp-axis__list">
              {organizers.map((item) => (
                <li key={item.label} className="mslp-axis__item">
                  <span className="mslp-axis__label">{item.label}</span>
                  <span className="mslp-axis__note">{item.note}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <h3 className="mslp-scope__subtitle">
          {isEn ? "Sort options, and export formats" : "並び順と、書き出せる形式"}
        </h3>
        <ul className="mslp-chips">
          {sorts.map((sort) => (
            <li key={sort}>{sort}</li>
          ))}
          <li className="mslp-chips__format">Markdown</li>
          <li className="mslp-chips__format">JSON</li>
          <li className="mslp-chips__format">CSV</li>
        </ul>

        <h3 className="mslp-scope__subtitle">
          {isEn ? "What sharing exposes" : "共有したときに出るもの・出ないもの"}
        </h3>
        <dl className="mslp-privacy">
          {privacyRows.map((row) => (
            <div key={row.label} className="mslp-privacy__row">
              <dt>{row.label}</dt>
              <dd>{row.note}</dd>
            </div>
          ))}
        </dl>

        <h3 className="mslp-scope__subtitle">
          {isEn ? "Before you rely on it, know this" : "使い始める前に知っておくこと"}
        </h3>
        <ul className="mslp-limits">
          {limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
