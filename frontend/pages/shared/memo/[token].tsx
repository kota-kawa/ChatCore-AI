import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import MarkdownContent from "../../../components/MarkdownContent";
import { formatDateTime } from "../../../lib/datetime";
import { fetchJson } from "../../../scripts/core/runtime_validation";

type SharedMemo = {
  title?: string;
  tags?: string;
  created_at?: string | null;
  input_content?: string;
  ai_response?: string;
};

type SharedMemoPayload = {
  memo?: SharedMemo;
  error?: string;
};

export default function SharedMemoPage() {
  const router = useRouter();
  const token = useMemo(() => {
    const raw = router.query.token;
    if (typeof raw === "string") return raw;
    if (Array.isArray(raw) && raw.length > 0) return raw[0];
    return "";
  }, [router.query.token]);
  const [loading, setLoading] = useState(true);
  const [payload, setPayload] = useState<SharedMemoPayload>({});

  useEffect(() => {
    if (!router.isReady || !token) return;

    setLoading(true);
    fetchJson<SharedMemoPayload>(`/memo/api/shared?token=${encodeURIComponent(token)}`)
      .then(({ response, payload: data }) => {
        if (!response.ok) {
          setPayload({ error: data.error || `共有メモの取得に失敗しました (${response.status})` });
          return;
        }
        setPayload(data);
      })
      .catch((error) => {
        setPayload({ error: error instanceof Error ? error.message : String(error) });
      })
      .finally(() => {
        setLoading(false);
      });
  }, [router.isReady, token]);

  const memo = payload.memo;
  const title = memo?.title || "共有メモ";
  const tags = memo?.tags ? memo.tags.split(/\s+/).filter(Boolean) : [];

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>{title} | Chat Core 共有</title>
        <link rel="stylesheet" href="/static/css/pages/shared_memo.css" />
      </Head>

      <div className="shared-memo-page">
        {loading && <div className="shared-memo-state">共有メモを読み込んでいます...</div>}

        {!loading && payload.error && <div className="shared-memo-state shared-memo-state--error">{payload.error}</div>}

        {!loading && !payload.error && memo && (
          <article className="shared-memo-shell">
            <header className="shared-memo-header">
              <h1>{title}</h1>
              {memo.created_at ? <p>保存日時: {formatDateTime(memo.created_at) || memo.created_at}</p> : null}
              <div className="shared-memo-tags">
                {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>タグなし</span>}
              </div>
            </header>

            <section className="shared-memo-section">
              <h2>入力内容</h2>
              <MarkdownContent text={memo.input_content || ""} className="md-content" />
            </section>

            <section className="shared-memo-section">
              <h2>AIの回答</h2>
              <MarkdownContent text={memo.ai_response || ""} className="md-content" />
            </section>
          </article>
        )}
      </div>
    </>
  );
}
