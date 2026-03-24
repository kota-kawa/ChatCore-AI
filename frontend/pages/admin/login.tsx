import Head from "next/head";
import { useRouter } from "next/router";
import { useState, type FormEvent } from "react";

type StatusMessage = {
  type: "success" | "error";
  text: string;
};

export default function AdminLogin() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<StatusMessage | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const messageTone =
    message?.type === "success"
      ? "border-emerald-400/70 bg-emerald-50 text-emerald-700"
      : "border-rose-400/70 bg-rose-50 text-rose-700";

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    setSubmitting(true);

    try {
      const res = await fetch("/admin/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          password,
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
      <Head>
        <meta charSet="UTF-8" />
        <title>管理者ログイン</title>
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      </Head>
      <div className="relative min-h-screen overflow-hidden bg-slate-50">
        <div className="pointer-events-none absolute -top-24 right-[-10rem] h-72 w-72 rounded-full bg-indigo-200/50 blur-3xl"></div>
        <div className="pointer-events-none absolute bottom-0 left-[-6rem] h-80 w-80 rounded-full bg-emerald-200/40 blur-3xl"></div>

        <div className="relative z-10 flex min-h-screen items-center justify-center px-6 py-12">
          <div className="w-full max-w-md rounded-3xl border border-white/70 bg-white/90 p-8 shadow-2xl shadow-indigo-100/50 backdrop-blur">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-2xl text-white shadow-lg shadow-indigo-200">
                🔐
              </span>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-indigo-500">
                  Admin Access
                </p>
                <h1 className="mt-2 text-2xl font-semibold text-slate-900">管理者ログイン</h1>
              </div>
            </div>

            <p className="mt-4 text-sm text-slate-500">
              セキュアな管理コンソールへアクセスするための認証です。
            </p>

            {message ? (
              <div
                className={`mt-6 rounded-2xl border border-transparent border-l-4 px-4 py-3 text-sm font-semibold ${messageTone}`}
              >
                {message.text}
              </div>
            ) : null}

            <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <label className="text-sm font-semibold text-slate-700" htmlFor="password">
                  パスワード
                </label>
                <input
                  type="password"
                  id="password"
                  name="password"
                  required
                  className="w-full rounded-2xl border border-slate-200 bg-white/90 px-4 py-3 text-sm text-slate-700 shadow-sm transition focus:border-indigo-400 focus:outline-none focus:ring-4 focus:ring-indigo-100"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              <button
                type="submit"
                className="cc-texture-btn cc-texture-btn--indigo w-full rounded-full bg-gradient-to-r from-indigo-600 to-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-200/60 transition hover:-translate-y-0.5 hover:shadow-indigo-300/70 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={submitting}
              >
                ログイン
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
