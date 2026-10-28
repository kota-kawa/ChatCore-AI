import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useState, type FormEvent, type MouseEvent } from "react";
import useSWR from "swr";

import { AdminTableOperations } from "../../components/admin/admin_table_operations";
import { AdminTablePreview, type ColumnDetail } from "../../components/admin/admin_table_preview";
import { DemoCodesPanel } from "../../components/admin/demo_codes_panel";
import { SeoHead } from "../../components/SeoHead";
import { Skeleton } from "../../components/ui/skeleton";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

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

function AdminTableListSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, index) => (
        <li className="admin-table-list__link" key={index}>
          <Skeleton variant="text" width={index % 2 === 0 ? "48%" : "62%"} height="0.95rem" />
        </li>
      ))}
    </>
  );
}

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
    isLoading,
    isValidating
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

  const showInitialSkeleton = isLoading && tables.length === 0 && columnNames.length === 0 && rows.length === 0;

  // 401エラー発生時はログインページへリダイレクトする
  // Redirect to login page when a 401 Unauthorized error is detected
  useEffect(() => {
    if (dashboardFetchError?.status !== 401) return;
    const nextPath = router.asPath || "/admin";
    void router.replace(`/admin/login?next=${encodeURIComponent(nextPath)}`);
  }, [dashboardFetchError, router]);

  // 管理者セッションが切れたときにログインページへ戻す（デモコード欄などの子コンポーネント用）
  // Send the admin back to the login page when the session is gone (for child panels such as demo codes)
  const redirectToAdminLogin = useCallback(() => {
    const nextPath = router.asPath || "/admin";
    void router.replace(`/admin/login?next=${encodeURIComponent(nextPath)}`);
  }, [router]);

  // フォームをAPIエンドポイントにPOSTして結果に応じてページを更新する
  // POST form data to an API endpoint and refresh the page based on the result
  const submitForm = async (event: FormEvent<HTMLFormElement>, endpoint: string) => {
    event.preventDefault();
    setLocalMessage(null);
    const formData = new FormData(event.currentTarget);

    try {
      const res = await resilientFetch(endpoint, {
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
      void router.replace(destination);
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
      await resilientFetch("/admin/api/logout", {
        method: "POST",
        credentials: "same-origin"
      });
    } finally {
      router.replace("/admin/login");
    }
  };

  // サーバーのフラッシュメッセージの分類を、お知らせの見た目に対応づける
  // Map a server flash category to a notice style
  const noticeTone = (category: string) =>
    category === "success" || category === "error" ? category : "info";

  return (
    <>
      <SeoHead
        title="管理コンソール | Chat Core"
        description="Chat Coreの管理コンソールです。"
        canonicalPath="/admin"
        noindex
      />
      <link rel="stylesheet" href="/static/css/pages/admin/admin.css" precedence="admin" />
      <div className="admin-console">
        <header className="admin-console__header">
          <div className="admin-console__header-inner">
            <div className="admin-console__brand">
              <p className="admin-console__eyebrow">Chat Core</p>
              <h1 className="admin-console__title">管理コンソール</h1>
            </div>
            <nav className="admin-console__nav" aria-label="管理メニュー">
              {/* 日本語: この「管理トップへ戻る」は /admin 自身へのリンクで、目的は再読み込みによる管理画面の初期化。
                       next/link ではクライアント遷移になり同一ルートでは何も起きないため、意図的に <a> を使う。
                  English: This "back to admin top" link points at /admin itself; the intent is a full reload that
                           resets the console. next/link would client-navigate to the same route and do nothing,
                           so a plain <a> is used deliberately. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a className="admin-btn" href="/admin">管理トップへ戻る</a>
              <a className="admin-btn" href="/admin/logout" onClick={handleLogout}>ログアウト</a>
            </nav>
          </div>
        </header>

        <main className="admin-console__main">
          {/* 読み込み状態・エラー・フラッシュメッセージ / Loading state, errors and flash messages */}
          <div className="admin-console__notices" aria-live="polite">
            {isValidating && !showInitialSkeleton ? (
              <p className="admin-notice admin-notice--info">管理データを更新しています…</p>
            ) : null}
            {dashboardFetchError && dashboardFetchError.status !== 401 ? (
              <p className="admin-notice admin-notice--error">{dashboardFetchError.message}</p>
            ) : null}
            {messages.map(([category, message], index) => (
              <p className={`admin-notice admin-notice--${noticeTone(category)}`} key={`${category}-${index}`}>
                {message}
              </p>
            ))}
            {localMessage ? (
              <p className={`admin-notice admin-notice--${localMessage.type}`}>{localMessage.text}</p>
            ) : null}
          </div>

          <div className="admin-console__content">
            <DemoCodesPanel onUnauthorized={redirectToAdminLogin} />

            <h2 className="admin-console__section-title">データベース</h2>
            <div className="admin-db">
              <nav className="admin-panel" aria-labelledby="adminTablesTitle">
                <h3 className="admin-panel__title" id="adminTablesTitle">テーブル一覧</h3>
                <ul className="admin-table-list">
                  {showInitialSkeleton ? (
                    <AdminTableListSkeleton />
                  ) : tables.length ? (
                    tables.map((table) => (
                      <li key={table}>
                        <a
                          className="admin-table-list__link"
                          href={`/admin?table=${encodeURIComponent(table)}`}
                          aria-current={table === selectedTable ? "page" : undefined}
                        >
                          {table}
                        </a>
                      </li>
                    ))
                  ) : (
                    <li className="admin-empty">テーブルが見つかりません。</li>
                  )}
                </ul>
              </nav>

              <div className="admin-db__main">
                <AdminTablePreview
                  loading={showInitialSkeleton}
                  selectedTable={selectedTable}
                  columnDetails={columnDetails}
                  columnNames={columnNames}
                  rows={rows}
                />
                <AdminTableOperations
                  selectedTable={selectedTable}
                  columnDetails={columnDetails}
                  dashboardError={dashboardError}
                  onSubmit={(event, endpoint) => void submitForm(event, endpoint)}
                />
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
