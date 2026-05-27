import React, { memo, useEffect, useMemo, useRef, useState } from "react";

import type { GenerativeUiArtifactV1 } from "../../lib/chat_page/types";

const SANDBOX_CSP = [
  "default-src 'none'",
  "img-src data: blob:",
  "style-src 'unsafe-inline'",
  "script-src 'unsafe-inline'",
  "connect-src 'none'",
  "media-src 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

const BASE_SANDBOX_CSS = `
html,body{margin:0;min-height:100%;background:transparent;color:#111827;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
*{box-sizing:border-box;}
button,input,select,textarea{font:inherit;}
button{cursor:pointer;}
.chatcore-empty-artifact{min-height:180px;margin:0;padding:18px;border:1px solid #d1d5db;border-radius:8px;background:#f8fafc;color:#111827;display:flex;flex-direction:column;justify-content:center;gap:8px;}
.chatcore-empty-artifact strong{font-size:15px;}
.chatcore-empty-artifact span{font-size:13px;line-height:1.5;color:#4b5563;}
`;

function escapeHtmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeScript(value: string) {
  return value.replace(/<\/script/gi, "<\\/script");
}

function escapeStyle(value: string) {
  return value.replace(/<\/style/gi, "<\\/style");
}

export function buildSandboxArtifactSrcDoc(artifact: GenerativeUiArtifactV1) {
  const title = escapeHtmlAttribute(artifact.title);
  const css = escapeStyle(`${BASE_SANDBOX_CSS}\n${artifact.css || ""}`);
  const js = escapeScript(artifact.js || "");
  const html = artifact.html || "";
  const shellScript = `
(function(){
  function send(type, payload){
    try { parent.postMessage(Object.assign({ type: type }, payload || {}), "*"); } catch (_) {}
  }
  function sendHeight(){
    var doc = document.documentElement;
    var body = document.body;
    var height = Math.max(
      doc ? doc.scrollHeight : 0,
      body ? body.scrollHeight : 0,
      doc ? doc.offsetHeight : 0,
      body ? body.offsetHeight : 0
    );
    send("chatcore-artifact-resize", { height: height });
  }
  function hasRenderableContent(){
    var body = document.body;
    if (!body) return false;
    var nodes = body.querySelectorAll("body > *:not(script):not(style)");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.id === "chatcore-empty-artifact") continue;
      var tag = String(node.tagName || "").toLowerCase();
      if (/^(canvas|svg|img|video|button|input|select|textarea)$/.test(tag)) return true;
      if (String(node.textContent || "").trim()) return true;
      var rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
      if (rect && rect.width > 2 && rect.height > 2) return true;
    }
    return false;
  }
  function ensureVisibleContent(){
    if (hasRenderableContent()) {
      var existing = document.getElementById("chatcore-empty-artifact");
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      sendHeight();
      return;
    }
    if (!document.getElementById("chatcore-empty-artifact")) {
      var fallback = document.createElement("section");
      fallback.id = "chatcore-empty-artifact";
      fallback.className = "chatcore-empty-artifact";
      var title = document.createElement("strong");
      title.textContent = "生成UIを表示しています";
      var note = document.createElement("span");
      note.textContent = "モデル出力が空だったため、安全な表示領域を補完しました。";
      fallback.appendChild(title);
      fallback.appendChild(note);
      document.body.appendChild(fallback);
    }
    sendHeight();
  }
  window.__chatcoreEnsureArtifactVisible = ensureVisibleContent;
  window.addEventListener("load", sendHeight);
  window.addEventListener("error", function(event){
    send("chatcore-artifact-error", { message: String(event.message || "Artifact script error") });
    setTimeout(ensureVisibleContent, 0);
  });
  if (typeof ResizeObserver === "function") {
    try { new ResizeObserver(sendHeight).observe(document.documentElement); } catch (_) {}
  }
  setTimeout(sendHeight, 0);
  setTimeout(sendHeight, 250);
  setTimeout(ensureVisibleContent, 400);
})();`;

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(SANDBOX_CSP)}">
<title>${title}</title>
<style>${css}</style>
</head>
<body>
${html}
<script>${shellScript}</script>
<script>
try {
${js}
} catch (error) {
  try { parent.postMessage({ type: "chatcore-artifact-error", message: String(error && error.message || error || "Artifact error") }, "*"); } catch (_) {}
}
try {
  if (typeof window.__chatcoreEnsureArtifactVisible === "function") {
    setTimeout(window.__chatcoreEnsureArtifactVisible, 0);
    setTimeout(window.__chatcoreEnsureArtifactVisible, 250);
  }
} catch (_) {}
</script>
</body>
</html>`;
}

type SandboxArtifactFrameProps = {
  artifact: GenerativeUiArtifactV1;
};

function clampHeight(value: number) {
  if (!Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.ceil(value), 160), 1200);
}

function SandboxArtifactFrameComponent({ artifact }: SandboxArtifactFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(() => artifact.height ?? 420);
  const [errorMessage, setErrorMessage] = useState("");
  const srcDoc = useMemo(() => buildSandboxArtifactSrcDoc(artifact), [artifact]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow || event.source !== iframeWindow) return;
      const data = event.data;
      if (!data || typeof data !== "object") return;

      if ((data as { type?: unknown }).type === "chatcore-artifact-resize") {
        const nextHeight = clampHeight((data as { height?: unknown }).height as number);
        if (nextHeight) setHeight(nextHeight);
        return;
      }

      if ((data as { type?: unknown }).type === "chatcore-artifact-error") {
        const message = (data as { message?: unknown }).message;
        setErrorMessage(typeof message === "string" ? message.slice(0, 180) : "Artifact error");
      }
    };

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, []);

  return (
    <section className="sandbox-artifact" aria-label={artifact.title}>
      <header className="sandbox-artifact__header">
        <div>
          <h3 className="sandbox-artifact__title">{artifact.title}</h3>
          {artifact.description ? (
            <p className="sandbox-artifact__description">{artifact.description}</p>
          ) : null}
        </div>
      </header>
      <iframe
        ref={iframeRef}
        className="sandbox-artifact__frame"
        title={artifact.title}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        srcDoc={srcDoc}
        style={{ height }}
      />
      {errorMessage ? (
        <p className="sandbox-artifact__error">生成UIの一部を実行できませんでした。</p>
      ) : null}
    </section>
  );
}

export const SandboxArtifactFrame = memo(SandboxArtifactFrameComponent);
SandboxArtifactFrame.displayName = "SandboxArtifactFrame";
