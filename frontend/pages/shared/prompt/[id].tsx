import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import MarkdownContent from "../../../components/MarkdownContent";
import { fetchJson } from "../../../scripts/core/runtime_validation";

type SharedPrompt = {
  id?: number | string;
  title?: string;
  category?: string;
  content?: string;
  author?: string;
  prompt_type?: string;
  reference_image_url?: string | null;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  created_at?: string;
};

type SharedPromptPayload = {
  prompt?: SharedPrompt;
  error?: string;
};

function formatDate(value?: string) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(parsed);
}

export default function SharedPromptPage() {
  const router = useRouter();
  const promptId = useMemo(() => {
    const raw = router.query.id;
    if (typeof raw === "string") return raw;
    if (Array.isArray(raw) && raw.length > 0) return raw[0];
    return "";
  }, [router.query.id]);
  const [loading, setLoading] = useState(true);
  const [payload, setPayload] = useState<SharedPromptPayload>({});

  useEffect(() => {
    if (!router.isReady || !promptId) return;

    setLoading(true);
    fetchJson<SharedPromptPayload>(`/prompt_share/api/prompts/${encodeURIComponent(promptId)}`)
      .then(({ response, payload: data }) => {
        if (!response.ok) {
          setPayload({ error: data.error || `共有プロンプトの取得に失敗しました (${response.status})` });
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
  }, [router.isReady, promptId]);

  const prompt = payload.prompt;
  const pageTitle = prompt?.title || "共有プロンプト";
  const promptTypeLabel = prompt?.prompt_type === "image" ? "画像生成プロンプト" : "通常プロンプト";

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>{pageTitle} | Chat Core 共有</title>
        <link rel="stylesheet" href="/static/css/pages/shared_prompt.css" />
      </Head>

      <div className="shared-prompt-page">
        {loading && <div className="shared-prompt-state">共有プロンプトを読み込んでいます...</div>}

        {!loading && payload.error && <div className="shared-prompt-state shared-prompt-state--error">{payload.error}</div>}

        {!loading && !payload.error && prompt && (
          <article className="shared-prompt-shell">
            <header className="shared-prompt-header">
              <span className="shared-prompt-pill">{promptTypeLabel}</span>
              <h1>{prompt.title || "共有プロンプト"}</h1>
              <div className="shared-prompt-meta">
                <span>カテゴリ: {prompt.category || "未分類"}</span>
                <span>投稿者: {prompt.author || "匿名ユーザー"}</span>
                {prompt.created_at ? <span>投稿日: {formatDate(prompt.created_at)}</span> : null}
                {prompt.ai_model ? <span>使用AI: {prompt.ai_model}</span> : null}
              </div>
            </header>

            {prompt.reference_image_url ? (
              <div className="shared-prompt-image">
                <img src={prompt.reference_image_url} alt={prompt.title || "共有プロンプトの作例画像"} />
              </div>
            ) : null}

            <section className="shared-prompt-section">
              <h2>内容</h2>
              <MarkdownContent text={prompt.content || ""} className="md-content" />
            </section>

            {prompt.input_examples ? (
              <section className="shared-prompt-section">
                <h2>入力例</h2>
                <MarkdownContent text={prompt.input_examples} className="md-content" />
              </section>
            ) : null}

            {prompt.output_examples ? (
              <section className="shared-prompt-section">
                <h2>出力例</h2>
                <MarkdownContent text={prompt.output_examples} className="md-content" />
              </section>
            ) : null}
          </article>
        )}
      </div>
    </>
  );
}
