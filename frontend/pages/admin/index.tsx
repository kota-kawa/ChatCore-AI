import { useRouter } from "next/router";
import { useEffect, useMemo, useState, type FormEvent, type MouseEvent } from "react";
import useSWR from "swr";

import { SeoHead } from "../../components/SeoHead";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

// テーブルの各カラムのメタ情報を表す型
// Type representing metadata for each column of a database table
type ColumnDetail = {
  name: string;
  type?: string | null;
  nullable?: boolean;
  key?: string | null;
  default?: string | number | null;
  extra?: string | null;
};

// フラッシュメッセージの型 [カテゴリ, テキスト]
// Flash message tuple type [category, text]
type FlashMessage = [string, string];

// フロントエンド内部で使用するダッシュボードデータの型
// Normalized dashboard data type used internally in the frontend
type AdminDashboardData = {
  tables: string[];
  selectedTable: string;
  columnNames: string[];
  columnDetails: ColumnDetail[];
  rows: Array<Array<unknown>>;
  error: string;
  messages: FlashMessage[];
};

// バックエンドAPIから返るレスポンスの型（snake_case）
// Raw API response type from the backend (snake_case keys)
type AdminDashboardResponse = {
  tables?: string[];
  selected_table?: string;
  column_names?: string[];
  column_details?: ColumnDetail[];
  rows?: Array<Array<unknown>>;
  error?: string;
  messages?: FlashMessage[];
};

// フォーム操作結果をUIに表示するためのローカルメッセージ型
// Local message type for displaying form operation results in the UI
type LocalMessage = {
  type: "success" | "error";
  text: string;
};

// HTTPステータスコードを保持するエラー型
// Error type that carries an HTTP status code
type HttpError = Error & {
  status?: number;
};

// SWRのフォールバック値として使用する空のダッシュボードデータ
// Empty dashboard data used as SWR fallback to avoid undefined checks
const EMPTY_DASHBOARD: AdminDashboardData = {
  tables: [],
  selectedTable: "",
  columnNames: [],
  columnDetails: [],
  rows: [],
  error: "",
  messages: []
};

// SWRのフェッチャー関数：APIからダッシュボードデータを取得してnormalizeする
// SWR fetcher: fetches dashboard data from the API and normalizes keys
const loadAdminDashboard = async (url: string): Promise<AdminDashboardData> => {
  const res = await resilientFetch(url, { credentials: "same-origin" });
  const data: AdminDashboardResponse = await res.json().catch(() => ({}));

  if (res.status === 401) {
    const error = new Error("管理者認証が必要です。") as HttpError;
    error.status = 401;
    throw error;
  }

  if (!res.ok) {
    const error = new Error(data.error || `ダッシュボード情報の取得に失敗しました (${res.status})`) as HttpError;
    error.status = res.status;
    throw error;
  }

  return {
    tables: Array.isArray(data.tables) ? data.tables : [],
    selectedTable: data.selected_table || "",
    columnNames: Array.isArray(data.column_names) ? data.column_names : [],
    columnDetails: Array.isArray(data.column_details) ? data.column_details : [],
    rows: Array.isArray(data.rows) ? data.rows : [],
    error: data.error || "",
    messages: Array.isArray(data.messages) ? data.messages : []
  };
};

// 管理コンソールのメインページコンポーネント
// Main page component for the admin console
export default function AdminDashboard() {
  const router = useRouter();

  // URLクエリパラメータからテーブル名を取得する（配列の場合は先頭要素を使用）
  // Extract table name from URL query params; use first element if array
  const selectedQueryTable = useMemo(() => {
    const raw = router.query.table;
    if (typeof raw === "string") return raw;
    if (Array.isArray(raw) && raw.length > 0) return raw[0];
    return "";
  }, [router.query.table]);

  // ルーターの準備完了後にのみAPIエンドポイントURLを構築する
  // Build the API endpoint URL only after the router is ready to avoid double-fetch
  const dashboardUrl = useMemo(() => {
    if (!router.isReady) return null;
    const query = selectedQueryTable ? `?table=${encodeURIComponent(selectedQueryTable)}` : "";
    return `/admin/api/dashboard${query}`;
  }, [router.isReady, selectedQueryTable]);

  // ダッシュボードデータを定期的に自動更新する（15秒ごと）
  // Auto-refresh dashboard data every 15 seconds to keep data current
  const {
    data: dashboard = EMPTY_DASHBOARD,
    error: dashboardFetchError,
    isLoading
  } = useSWR<AdminDashboardData, HttpError>(dashboardUrl, loadAdminDashboard, {
    revalidateOnFocus: true,
    refreshInterval: 15000,
    dedupingInterval: 5000,
    keepPreviousData: true
  });

  const [localMessage, setLocalMessage] = useState<LocalMessage | null>(null);
  const {
    tables,
    selectedTable,
    columnNames,
    columnDetails,
    rows,
    error: dashboardError,
    messages
  } = dashboard;

  // カラムが1つしかない場合は削除を禁止する（テーブルを壊さないため）
  // Disable column deletion when only one column exists to prevent table corruption
  const deleteDisabled = columnDetails.length <= 1;

  // 長いテキストコンテンツを持つカラムは表示幅を広げる
  // Widen display columns known to contain long text content
  const wideColumns = [
    "message",
    "content",
    "prompt_template",
    "input_examples",
    "output_examples"
  ];

  // 共通UIスタイルクラスをまとめて定義することで一貫性を保つ
  // Centralized style class definitions for UI consistency across the page
  const panelClass =
    "rounded-3xl border border-white/70 bg-white/80 p-6 shadow-xl shadow-indigo-100/40 backdrop-blur";
  const labelClass = "text-sm font-semibold text-slate-700";
  const inputClass =
    "w-full rounded-2xl border border-slate-200 bg-white/90 px-4 py-2.5 text-sm text-slate-700 shadow-sm transition focus:border-indigo-400 focus:outline-none focus:ring-4 focus:ring-indigo-100";
  const buttonClass =
    "cc-texture-btn cc-texture-btn--indigo rounded-full bg-gradient-to-r from-indigo-600 to-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-200/60 transition hover:-translate-y-0.5 hover:shadow-indigo-300/70 disabled:cursor-not-allowed disabled:opacity-60";

  // メッセージカテゴリに応じたTailwindクラスを返すヘルパー
  // Returns Tailwind classes based on flash message category
  const flashTone = (category: string) => {
    if (category === "success") {
      return "border-emerald-400/70 bg-emerald-50 text-emerald-700";
    }
    if (category === "error") {
      return "border-rose-400/70 bg-rose-50 text-rose-700";
    }
    return "border-slate-200 bg-slate-50 text-slate-600";
  };

  // 幅広カラムとそれ以外でセルの表示幅クラスを切り替える
  // Switch cell width class between wide and standard based on column name
  const cellWidthClass = (columnName: string) =>
    wideColumns.includes(columnName) ? "min-w-[240px] max-w-[420px]" : "min-w-[140px]";

  // 401エラー発生時はログインページへリダイレクトする
  // Redirect to login page when a 401 Unauthorized error is detected
  useEffect(() => {
    if (dashboardFetchError?.status !== 401) return;
    const nextPath = router.asPath || "/admin";
    void router.replace(`/admin/login?next=${encodeURIComponent(nextPath)}`);
  }, [dashboardFetchError, router]);

  // フォームをAPIエンドポイントにPOSTして結果に応じてページを更新する
  // POST form data to an API endpoint and refresh the page based on the result
  const submitForm = async (event: FormEvent<HTMLFormElement>, endpoint: string) => {
    event.preventDefault();
    setLocalMessage(null);
    const formData = new FormData(event.currentTarget);

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        body: formData
      });
      if (res.status === 401) {
        const nextPath = router.asPath || "/admin";
        void router.replace(`/admin/login?next=${encodeURIComponent(nextPath)}`);
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status === "fail") {
        throw new Error(data.error || "操作に失敗しました。");
      }
      const destination = data.redirect || router.asPath || "/admin";
      router.replace(destination);
    } catch (err) {
      setLocalMessage({
        type: "error",
        text: err instanceof Error ? err.message : "操作に失敗しました。"
      });
    }
  };

  // ログアウトAPIを呼び出してからログインページへ遷移する
  // Call logout API then navigate to the login page regardless of the outcome
  const handleLogout = async (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    try {
      await fetch("/admin/api/logout", {
        method: "POST",
        credentials: "same-origin"
      });
    } finally {
      router.replace("/admin/login");
    }
  };

  return (
    <>
      <SeoHead
        title="管理コンソール | Chat Core"
        description="Chat Coreの管理コンソールです。"
        canonicalPath="/admin"
        noindex
      />
      <div className="relative min-h-screen overflow-hidden bg-slate-50">
        {/* 背景の装飾的なぼかし円（ポインターイベントを無効化）/ Decorative blurred circles in background, non-interactive */}
        <div className="pointer-events-none absolute -top-24 right-[-12rem] h-72 w-72 rounded-full bg-indigo-200/50 blur-3xl"></div>
        <div className="pointer-events-none absolute top-40 -left-24 h-96 w-96 rounded-full bg-emerald-200/40 blur-3xl"></div>

        {/* 画面上部に固定されたナビゲーションヘッダー / Sticky navigation header fixed at the top */}
        <header className="sticky top-0 z-20 border-b border-white/60 bg-white/80 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-600 text-xl text-white shadow-lg shadow-indigo-200">
                ⚙️
              </span>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.35em] text-indigo-500">
                  Admin Console
                </p>
                <h1 className="text-xl font-semibold text-slate-900">管理コンソール</h1>
              </div>
            </div>
            <nav className="flex flex-wrap gap-3">
              <a
                className="cc-texture-btn cc-texture-btn--light cc-texture-btn--light-indigo inline-flex items-center justify-center rounded-full border border-indigo-200 bg-white px-4 py-2 text-xs font-semibold text-indigo-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-indigo-50"
                href="/admin"
              >
                管理トップへ戻る
              </a>
              <a
                className="cc-texture-btn cc-texture-btn--light inline-flex items-center justify-center rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-50"
                href="/admin/logout"
                onClick={handleLogout}
              >
                ログアウト
              </a>
            </nav>
          </div>
        </header>

        <main className="relative z-10 mx-auto max-w-6xl px-6 py-10 lg:py-12">
          {/* ローディング状態・エラー・フラッシュメッセージを表示するエリア / Area for loading state, errors, and flash messages */}
          <div className="mb-8 grid gap-3">
            {isLoading ? (
              <div className="rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm font-semibold text-indigo-700">
                管理データを読み込んでいます...
              </div>
            ) : null}
            {dashboardFetchError && dashboardFetchError.status !== 401 ? (
              <div className="rounded-2xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
                {dashboardFetchError.message}
              </div>
            ) : null}
            {/* サーバーサイドのフラッシュメッセージを表示する / Render server-side flash messages */}
            {messages.map(([category, message], index) => (
              <div
                className={`rounded-2xl border border-transparent border-l-4 px-4 py-3 text-sm font-semibold ${flashTone(
                  category
                )}`}
                key={`${category}-${index}`}
              >
                {message}
              </div>
            ))}
            {/* クライアントサイドのフォーム操作結果メッセージを表示する / Render client-side form operation result message */}
            {localMessage ? (
              <div
                className={`rounded-2xl border border-transparent border-l-4 px-4 py-3 text-sm font-semibold ${flashTone(
                  localMessage.type
                )}`}
              >
                {localMessage.text}
              </div>
            ) : null}
          </div>

          {/* テーブル一覧パネルと操作パネルを2カラムレイアウトで並べる / Two-column layout: table list panel on left, operations panel on right */}
          <div className="grid gap-8 xl:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
            {/* 左カラム：テーブル一覧と削除フォーム / Left column: table list and delete table form */}
            <section className={panelClass}>
              <h2 className="text-lg font-semibold text-slate-900">テーブル一覧</h2>
              <ul className="mt-4 space-y-3">
                {tables.length ? (
                  tables.map((table) => (
                    <li
                      className="flex items-center justify-between gap-3 rounded-2xl border border-slate-100 bg-white/80 px-4 py-3 text-sm shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
                      key={table}
                    >
                      <span className="font-semibold text-slate-700">{table}</span>
                      <a
                        className="cc-texture-btn cc-texture-btn--light cc-texture-btn--light-indigo inline-flex items-center rounded-full border border-indigo-200 bg-white px-3 py-1 text-xs font-semibold text-indigo-600 transition hover:bg-indigo-50"
                        href={`/admin?table=${encodeURIComponent(table)}`}
                      >
                        開く
                      </a>
                    </li>
                  ))
                ) : (
                  <li className="rounded-2xl border border-dashed border-slate-200 bg-white/60 px-4 py-3 text-sm text-slate-500">
                    テーブルが見つかりません。
                  </li>
                )}
              </ul>

              {/* テーブル削除フォーム：誤操作防止のため手入力を必須とする / Table deletion form: requires manual input to prevent accidental deletion */}
              <form className="mt-6 space-y-4" onSubmit={(event) => submitForm(event, "/admin/api/delete-table")}>
                <h3 className="text-base font-semibold text-slate-700">テーブルの削除</h3>
                <div className="space-y-2">
                  <label className={labelClass} htmlFor="delete-table-name">
                    テーブル名
                  </label>
                  <input type="text" id="delete-table-name" name="table_name" required className={inputClass} />
                </div>
                <button
                  type="submit"
                  className="cc-texture-btn cc-texture-btn--danger rounded-full bg-gradient-to-r from-rose-500 to-rose-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-rose-200/60 transition hover:-translate-y-0.5 hover:shadow-rose-300/70"
                >
                  削除
                </button>
              </form>
            </section>

            {/* 右カラム：テーブルプレビューとカラム操作フォーム / Right column: table preview and column operation forms */}
            <div className="space-y-8">
              {/* テーブルプレビューセクション：定義と最大100件のデータ行を表示 / Table preview section: shows schema definition and up to 100 data rows */}
              <section className={panelClass}>
                <h2 className="text-lg font-semibold text-slate-900">テーブルプレビュー</h2>
                {selectedTable ? (
                  <>
                    <p className="mt-3 text-sm text-slate-500">
                      最大100件の行を表示しています：<strong className="text-slate-700">{selectedTable}</strong>
                    </p>
                    {columnDetails.length ? (
                      <div className="mt-6">
                        <h3 className="text-base font-semibold text-slate-700">テーブル定義</h3>
                        <div className="mt-3 overflow-x-auto rounded-2xl border border-slate-100 bg-white">
                          <table className="min-w-full text-left text-sm text-slate-700">
                            <thead className="bg-slate-100/70 text-xs font-semibold uppercase tracking-wide text-slate-500">
                              <tr>
                                <th className="px-4 py-3">カラム名</th>
                                <th className="px-4 py-3">型</th>
                                <th className="px-4 py-3">NULL</th>
                                <th className="px-4 py-3">キー</th>
                                <th className="px-4 py-3">デフォルト</th>
                                <th className="px-4 py-3">追加情報</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {columnDetails.map((column) => (
                                <tr className="even:bg-slate-50/60" key={column.name}>
                                  <td className="px-4 py-3">{column.name}</td>
                                  <td className="px-4 py-3">{column.type}</td>
                                  <td className="px-4 py-3">{column.nullable ? "許可" : "不可"}</td>
                                  <td className="px-4 py-3">{column.key || "—"}</td>
                                  <td className="px-4 py-3">
                                    {column.default !== null && column.default !== undefined
                                      ? column.default
                                      : "—"}
                                  </td>
                                  <td className="px-4 py-3">{column.extra || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    ) : null}

                    {columnNames.length ? (
                      <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-100 bg-white">
                        <table className="min-w-full text-left text-sm text-slate-700">
                          <thead className="bg-slate-100/70 text-xs font-semibold uppercase tracking-wide text-slate-500">
                            <tr>
                              {columnNames.map((column) => (
                                <th className={`px-4 py-3 ${cellWidthClass(column)}`} key={column}>
                                  {column}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {rows.length ? (
                              rows.map((row, rowIndex) => (
                                <tr className="even:bg-slate-50/60" key={rowIndex}>
                                  {row.map((value, colIndex) => {
                                    const columnName = columnNames[colIndex];
                                    const cellText = value === null || value === undefined ? "" : String(value);
                                    // 160文字を超える長いテキストはdetails要素で折りたたむ
                                    // Collapse long text exceeding 160 chars inside a details element
                                    if (cellText.length > 160) {
                                      const summaryText = cellText
                                        .slice(0, 160)
                                        .replace(/\n/g, " ")
                                        .replace(/\r/g, " ");
                                      return (
                                        <td className={`px-4 py-3 align-top ${cellWidthClass(columnName)}`} key={`${rowIndex}-${colIndex}`}>
                                          <details className="group rounded-xl border border-slate-200/70 bg-slate-50/80 p-3 text-sm text-slate-700">
                                            <summary className="flex cursor-pointer list-none items-start gap-2 text-indigo-600">
                                              <span className="flex-1 truncate">{summaryText}…</span>
                                              <span className="ml-auto text-indigo-400 group-open:hidden">＋</span>
                                              <span className="ml-auto hidden text-indigo-400 group-open:inline">−</span>
                                            </summary>
                                            <div className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                                              {cellText}
                                            </div>
                                          </details>
                                        </td>
                                      );
                                    }
                                    return (
                                      <td className={`px-4 py-3 align-top ${cellWidthClass(columnName)}`} key={`${rowIndex}-${colIndex}`}>
                                        <div className="whitespace-pre-wrap text-sm text-slate-700">{cellText}</div>
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))
                            ) : (
                              <tr>
                                <td className="px-4 py-4 text-sm text-slate-500" colSpan={columnNames.length}>
                                  表示できるデータがありません。
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-slate-500">表示できるデータがありません。</p>
                    )}
                  </>
                ) : (
                  <p className="mt-3 text-sm text-slate-500">内容を確認するテーブルを選択してください。</p>
                )}
              </section>

              {/* テーブル操作セクション：テーブル選択時はカラム追加/削除、未選択時はテーブル作成を表示 / Table operations: show column add/delete when table selected, else show create table form */}
              <section className={panelClass}>
                <h2 className="text-lg font-semibold text-slate-900">テーブル操作</h2>
                {selectedTable ? (
                  <>
                    <h3 className="mt-4 text-base font-semibold text-slate-700">カラムの追加</h3>
                    <form className="mt-3 space-y-4" onSubmit={(event) => submitForm(event, "/admin/api/add-column")}>
                      <input type="hidden" name="table_name" value={selectedTable} />
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="add-column-name">
                          カラム名
                        </label>
                        <input type="text" id="add-column-name" name="column_name" required className={inputClass} />
                      </div>
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="add-column-type">
                          カラム定義（例：VARCHAR(255) NOT NULL / NUMERIC(10,2) DEFAULT 0）
                        </label>
                        <input type="text" id="add-column-type" name="column_type" required className={inputClass} />
                      </div>
                      <button type="submit" className={buttonClass}>
                        カラムを追加
                      </button>
                    </form>

                    <h3 className="mt-6 text-base font-semibold text-slate-700">カラムの削除</h3>
                    <form className="mt-3 space-y-4" onSubmit={(event) => submitForm(event, "/admin/api/delete-column")}>
                      <input type="hidden" name="table_name" value={selectedTable} />
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="delete-column-name">
                          削除するカラム
                        </label>
                        <select
                          id="delete-column-name"
                          name="column_name"
                          disabled={deleteDisabled}
                          required
                          defaultValue=""
                          className={inputClass}
                        >
                          <option value="" disabled>
                            カラムを選択
                          </option>
                          {columnDetails.map((column) => (
                            <option value={column.name} key={column.name}>
                              {column.name}
                              {column.type ? ` (${column.type})` : ""}
                            </option>
                          ))}
                        </select>
                      </div>
                      <button type="submit" className={buttonClass} disabled={deleteDisabled}>
                        カラムを削除
                      </button>
                      {deleteDisabled ? (
                        <p className="text-xs font-semibold text-rose-600">
                          テーブルのカラムが1つしかないため削除できません。
                        </p>
                      ) : null}
                    </form>
                  </>
                ) : (
                  <>
                    <p className="mt-3 text-sm text-slate-500">カラムの変更を行うテーブルを選択してください。</p>

                    {/* テーブル作成フォーム：PostgreSQLのカラム定義をSQL形式で入力する / Table creation form: accepts PostgreSQL column definitions in SQL syntax */}
                    <h3 className="mt-6 text-base font-semibold text-slate-700">テーブルの作成</h3>
                    <form className="mt-3 space-y-4" onSubmit={(event) => submitForm(event, "/admin/api/create-table")}>
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="create-table-name">
                          テーブル名
                        </label>
                        <input type="text" id="create-table-name" name="table_name" required className={inputClass} />
                      </div>
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="column-definitions">
                          カラム定義
                        </label>
                        <textarea
                          id="column-definitions"
                          name="columns"
                          placeholder="id BIGSERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL"
                          required
                          className={`${inputClass} min-h-[140px]`}
                        ></textarea>
                      </div>
                      <p className="text-xs text-slate-500">現在は PostgreSQL の基本的なカラム定義のみ対応しています。テーブルオプションは利用できません。</p>
                      <button type="submit" className={buttonClass}>
                        作成
                      </button>
                    </form>
                  </>
                )}

                {dashboardError ? <p className="mt-4 text-sm font-semibold text-rose-600">エラー：{dashboardError}</p> : null}
              </section>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
