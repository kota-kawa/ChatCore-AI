import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState, type FormEvent, type MouseEvent } from "react";
import useSWR from "swr";

type ColumnDetail = {
  name: string;
  type?: string | null;
  nullable?: boolean;
  key?: string | null;
  default?: string | number | null;
  extra?: string | null;
};

type FlashMessage = [string, string];

type AdminDashboardData = {
  tables: string[];
  selectedTable: string;
  columnNames: string[];
  columnDetails: ColumnDetail[];
  rows: Array<Array<unknown>>;
  error: string;
  messages: FlashMessage[];
};

type AdminDashboardResponse = {
  tables?: string[];
  selected_table?: string;
  column_names?: string[];
  column_details?: ColumnDetail[];
  rows?: Array<Array<unknown>>;
  error?: string;
  messages?: FlashMessage[];
};

type LocalMessage = {
  type: "success" | "error";
  text: string;
};

type HttpError = Error & {
  status?: number;
};

const EMPTY_DASHBOARD: AdminDashboardData = {
  tables: [],
  selectedTable: "",
  columnNames: [],
  columnDetails: [],
  rows: [],
  error: "",
  messages: []
};

const loadAdminDashboard = async (url: string): Promise<AdminDashboardData> => {
  const res = await fetch(url, { credentials: "same-origin" });
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

export default function AdminDashboard() {
  const router = useRouter();
  const selectedQueryTable = useMemo(() => {
    const raw = router.query.table;
    if (typeof raw === "string") return raw;
    if (Array.isArray(raw) && raw.length > 0) return raw[0];
    return "";
  }, [router.query.table]);
  const dashboardUrl = useMemo(() => {
    if (!router.isReady) return null;
    const query = selectedQueryTable ? `?table=${encodeURIComponent(selectedQueryTable)}` : "";
    return `/admin/api/dashboard${query}`;
  }, [router.isReady, selectedQueryTable]);
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
  const deleteDisabled = columnDetails.length <= 1;
  const wideColumns = [
    "message",
    "content",
    "prompt_template",
    "input_examples",
    "output_examples"
  ];
  const panelClass =
    "rounded-3xl border border-white/70 bg-white/80 p-6 shadow-xl shadow-indigo-100/40 backdrop-blur";
  const labelClass = "text-sm font-semibold text-slate-700";
  const inputClass =
    "w-full rounded-2xl border border-slate-200 bg-white/90 px-4 py-2.5 text-sm text-slate-700 shadow-sm transition focus:border-indigo-400 focus:outline-none focus:ring-4 focus:ring-indigo-100";
  const buttonClass =
    "cc-texture-btn cc-texture-btn--indigo rounded-full bg-gradient-to-r from-indigo-600 to-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-200/60 transition hover:-translate-y-0.5 hover:shadow-indigo-300/70 disabled:cursor-not-allowed disabled:opacity-60";
  const flashTone = (category: string) => {
    if (category === "success") {
      return "border-emerald-400/70 bg-emerald-50 text-emerald-700";
    }
    if (category === "error") {
      return "border-rose-400/70 bg-rose-50 text-rose-700";
    }
    return "border-slate-200 bg-slate-50 text-slate-600";
  };
  const cellWidthClass = (columnName: string) =>
    wideColumns.includes(columnName) ? "min-w-[240px] max-w-[420px]" : "min-w-[140px]";

  useEffect(() => {
    if (dashboardFetchError?.status !== 401) return;
    const nextPath = router.asPath || "/admin";
    void router.replace(`/admin/login?next=${encodeURIComponent(nextPath)}`);
  }, [dashboardFetchError, router]);

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
      <Head>
        <meta charSet="UTF-8" />
        <title>管理コンソール</title>
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      </Head>
      <div className="relative min-h-screen overflow-hidden bg-slate-50">
        <div className="pointer-events-none absolute -top-24 right-[-12rem] h-72 w-72 rounded-full bg-indigo-200/50 blur-3xl"></div>
        <div className="pointer-events-none absolute top-40 -left-24 h-96 w-96 rounded-full bg-emerald-200/40 blur-3xl"></div>

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

          <div className="grid gap-8 xl:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
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

            <div className="space-y-8">
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
                          カラム定義（例：VARCHAR(255) NOT NULL）
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
                          カラム定義（SQL）
                        </label>
                        <textarea
                          id="column-definitions"
                          name="columns"
                          placeholder="id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(255) NOT NULL"
                          required
                          className={`${inputClass} min-h-[140px]`}
                        ></textarea>
                      </div>
                      <div className="space-y-2">
                        <label className={labelClass} htmlFor="table-options">
                          テーブルオプション（例：ENGINE=InnoDB DEFAULT CHARSET=utf8mb4）
                        </label>
                        <input
                          type="text"
                          id="table-options"
                          name="table_options"
                          placeholder="ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
                          className={inputClass}
                        />
                      </div>
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
