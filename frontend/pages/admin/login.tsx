import { useRouter } from "next/router";
import { useState, type FormEvent } from "react";

import { SeoHead } from "../../components/SeoHead";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

// ステータスメッセージの型定義（成功・エラーの2種類）
// Type definition for status messages (success or error)
type StatusMessage = {
  type: "success" | "error";
  text: string;
};

// 管理者ログインページコンポーネント（検索エンジンには非公開）
// Admin login page component (excluded from search engine indexing)
export default function AdminLogin() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<StatusMessage | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // ログインフォームの送信処理（管理者ログインAPIを呼び出してリダイレクトする）
  // Handle login form submission (call admin login API and redirect on success)
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    setSubmitting(true);

    try {
      const res = await resilientFetch("/admin/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          password,
          // nextパラメータがある場合はログイン後にそのパスへ戻る
          // Redirect to the next path after login if specified
          next: router.query.next || ""
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status === "fail") {
        throw new Error(data.error || "Invalid password.");
      }
      const destination = data.redirect || "/admin";
      router.replace(destination);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Invalid password."
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <SeoHead
        title="管理者ログイン | Chat Core"
        description="Chat Coreの管理者ログインページです。"
        canonicalPath="/admin/login"
        noindex
      />
      <link rel="stylesheet" href="/static/css/pages/admin/admin.css" precedence="admin" />
      <main className="admin-login">
        <div className="admin-login__card">
          <div>
            <h1 className="admin-login__title">管理者ログイン</h1>
            <p className="admin-login__lead">Chat Core の管理コンソールに入るためのパスワードを入力してください。</p>
          </div>

          {/* 送信後のエラーまたは成功メッセージ / Error or success message after submission */}
          {message ? (
            <p className={`admin-notice admin-notice--${message.type}`} role="alert">
              {message.text}
            </p>
          ) : null}

          <form className="admin-form" onSubmit={handleSubmit}>
            <div className="admin-field">
              <label className="admin-label" htmlFor="password">パスワード</label>
              <input
                type="password"
                id="password"
                name="password"
                required
                autoComplete="current-password"
                className="admin-input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            {/* 送信中はボタンを無効化する / Disable button while submitting */}
            <button type="submit" className="admin-btn admin-btn--primary admin-btn--block" disabled={submitting}>
              ログイン
            </button>
          </form>
        </div>
      </main>
    </>
  );
}
