import React, { memo, useEffect, useMemo, useRef, useState } from "react";

import type { GenerativeUiArtifactV1 } from "../../lib/chat_page/types";

// サンドボックスiframeに適用するContent Security Policy（外部接続・フォームなどを完全ブロック）
// scriptSourcesには、インラインに加えて許可するローカル配信ライブラリのURLだけを渡す
// Content Security Policy for sandbox iframe (fully blocks external connections, forms, etc.)
// scriptSources receives only the locally served library URLs allowed in addition to inline
function buildSandboxCsp(scriptSources: string[]) {
  return [
    "default-src 'none'",
    "img-src data: blob:",
    "style-src 'unsafe-inline'",
    `script-src ${["'unsafe-inline'", ...scriptSources].join(" ")}`,
    "connect-src 'none'",
    "media-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
}

// ローカル配信するThree.js（UMDビルド）のパス。CDNはCSPで遮断されるため自オリジンから配信する
// Path of the locally served Three.js (UMD build); CDNs are blocked by the CSP,
// so it is served from our own origin
const THREE_VENDOR_SCRIPT_PATH = "/static/js/vendor/three.min.js";

// アーティファクトが要求するライブラリを、自オリジンの絶対URLに解決する
// Resolve the libraries requested by the artifact into absolute same-origin URLs
function resolveLibraryScriptUrls(artifact: GenerativeUiArtifactV1) {
  if (!artifact.libraries?.includes("three")) return [];
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return [`${origin}${THREE_VENDOR_SCRIPT_PATH}`];
}

// Several providers emit the familiar OrbitControls addon import even when the
// prompt asks for core-only Three.js. The backend removes that network import;
// this small local control preserves the expected drag-to-orbit behavior.
function buildThreeCompatibilityScript(artifact: GenerativeUiArtifactV1) {
  if (!artifact.libraries?.includes("three") || !/\bOrbitControls\b/.test(artifact.js || "")) {
    return "";
  }
  return `
(function(){
  if (typeof THREE === "undefined" || typeof window.OrbitControls === "function") return;
  function OrbitControls(camera, element){
    this.object=camera;this.domElement=element;this.target=new THREE.Vector3();
    this.enabled=true;this.enableDamping=false;this.dampingFactor=.08;
    this.enableZoom=true;this.autoRotate=false;this.autoRotateSpeed=2;
    var self=this,drag=false,x=0,y=0,theta=0,phi=0,radius=1;
    function sync(){var offset=camera.position.clone().sub(self.target);radius=Math.max(.1,offset.length());theta=Math.atan2(offset.x,offset.z);phi=Math.acos(Math.max(-1,Math.min(1,offset.y/radius)));}
    function apply(){phi=Math.max(.05,Math.min(Math.PI-.05,phi));camera.position.set(self.target.x+radius*Math.sin(phi)*Math.sin(theta),self.target.y+radius*Math.cos(phi),self.target.z+radius*Math.sin(phi)*Math.cos(theta));camera.lookAt(self.target);}
    sync();
    element.addEventListener("pointerdown",function(e){if(!self.enabled)return;drag=true;x=e.clientX;y=e.clientY;if(element.setPointerCapture)element.setPointerCapture(e.pointerId);});
    element.addEventListener("pointermove",function(e){if(!drag||!self.enabled)return;theta-=(e.clientX-x)*.008;phi-=(e.clientY-y)*.008;x=e.clientX;y=e.clientY;apply();});
    element.addEventListener("pointerup",function(){drag=false;});
    element.addEventListener("wheel",function(e){if(!self.enabled||!self.enableZoom)return;e.preventDefault();radius*=Math.exp(e.deltaY*.001);radius=Math.max(.2,Math.min(200,radius));apply();},{passive:false});
    this.update=function(){if(self.autoRotate&&!drag){theta+=self.autoRotateSpeed*.001;apply();}else{camera.lookAt(self.target);}return true;};
    this.dispose=function(){};
  }
  window.OrbitControls=OrbitControls;THREE.OrbitControls=OrbitControls;
})();`;
}

// フレームの高さの最小・最大・デフォルト値（px）
// Minimum, maximum, and default frame heights (px)
const MIN_FRAME_HEIGHT = 160;
const MAX_FRAME_HEIGHT = 900;
const DEFAULT_FRAME_HEIGHT = 420;

// サンドボックス内に適用するベースCSSリセット
// Base CSS reset applied inside the sandbox
const BASE_SANDBOX_CSS = `
html,body{margin:0;min-height:100%;background:transparent;color:#111827;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere;}
*{box-sizing:border-box;}
img,svg,canvas,video{max-width:100%;height:auto;}
table{max-width:100%;border-collapse:collapse;}
pre{max-width:100%;overflow:auto;}
button,input,select,textarea{font:inherit;}
button{cursor:pointer;}
a{color:inherit;}
#chatcore-artifact-root{display:block;min-height:160px;width:100%;overflow:auto;}
.chatcore-empty-artifact{min-height:180px;margin:0;padding:18px;border:1px solid #d1d5db;border-radius:8px;background:#f8fafc;color:#111827;display:flex;flex-direction:column;justify-content:center;gap:8px;}
.chatcore-empty-artifact strong{font-size:15px;}
.chatcore-empty-artifact span{font-size:13px;line-height:1.5;color:#4b5563;}
`;

// HTML属性値のエスケープ（XSS防止）
// Escape HTML attribute values (XSS prevention)
function escapeHtmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// </script>タグが途中で閉じてしまうのを防ぐエスケープ
// Escape to prevent </script> tag from prematurely closing
function escapeScript(value: string) {
  return value.replace(/<\/script/gi, "<\\/script");
}

// </style>タグが途中で閉じてしまうのを防ぐエスケープ
// Escape to prevent </style> tag from prematurely closing
function escapeStyle(value: string) {
  return value.replace(/<\/style/gi, "<\\/style");
}

// アーティファクトをiframeのsrcdocとして埋め込むHTMLを生成する（CSP・高さ自動調整スクリプト込み）
// Generate the srcdoc HTML to embed an artifact in an iframe (includes CSP and auto-height script)
export function buildSandboxArtifactSrcDoc(artifact: GenerativeUiArtifactV1) {
  const title = escapeHtmlAttribute(artifact.title);
  const css = escapeStyle(`${BASE_SANDBOX_CSS}\n${artifact.css || ""}`);
  const js = escapeScript(artifact.js || "");
  const html = artifact.html || "";
  const libraryScriptUrls = resolveLibraryScriptUrls(artifact);
  const threeCompatibilityScript = buildThreeCompatibilityScript(artifact);
  const libraryScriptTags = libraryScriptUrls
    .map((url) => `<script src="${escapeHtmlAttribute(url)}"></script>`)
    .join("\n");
  // ライブラリの読み込みに失敗した場合は、ユーザーJSを実行せずにエラー経路へ流す
  // If the library failed to load, route to the error path instead of running the user JS
  const libraryGuard = artifact.libraries?.includes("three")
    ? 'if (typeof THREE === "undefined") { throw new Error("Three.js failed to load"); }\n'
    : "";
  const shellScript = `
(function(){
  var MIN_HEIGHT = ${MIN_FRAME_HEIGHT};
  var MAX_HEIGHT = ${MAX_FRAME_HEIGHT};
  var resizePending = false;
  function root(){
    return document.getElementById("chatcore-artifact-root") || document.body;
  }
  function send(type, payload){
    try { parent.postMessage(Object.assign({ type: type }, payload || {}), "*"); } catch (_) {}
  }
  function clampHeight(value){
    if (!isFinite(value)) return MIN_HEIGHT;
    return Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, Math.ceil(value)));
  }
  function sendHeight(){
    resizePending = false;
    var doc = document.documentElement;
    var body = document.body;
    var height = Math.max(
      doc ? doc.scrollHeight : 0,
      body ? body.scrollHeight : 0,
      doc ? doc.offsetHeight : 0,
      body ? body.offsetHeight : 0
    );
    send("chatcore-artifact-resize", { height: clampHeight(height) });
  }
  function requestHeight(){
    if (resizePending) return;
    resizePending = true;
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(sendHeight);
    } else {
      setTimeout(sendHeight, 16);
    }
  }
  function hasRenderableContent(){
    var container = root();
    if (!container) return false;
    var nodes = container.children || [];
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.id === "chatcore-empty-artifact") continue;
      var tag = String(node.tagName || "").toLowerCase();
      if (tag === "script" || tag === "style") continue;
      if (/^(canvas|svg|img|video|button|input|select|textarea)$/.test(tag)) return true;
      if (node.querySelector && node.querySelector("canvas,svg,img,video,button,input,select,textarea")) return true;
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
      requestHeight();
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
      root().appendChild(fallback);
    }
    requestHeight();
  }
  function reportError(message){
    send("chatcore-artifact-error", { message: String(message || "Artifact script error") });
    setTimeout(ensureVisibleContent, 0);
  }
  window.__chatcoreEnsureArtifactVisible = ensureVisibleContent;
  window.__chatcoreReportArtifactError = reportError;
  window.addEventListener("load", requestHeight);
  window.addEventListener("error", function(event){
    reportError(event.message);
  });
  if (typeof ResizeObserver === "function") {
    try { new ResizeObserver(requestHeight).observe(document.documentElement); } catch (_) {}
    try { new ResizeObserver(requestHeight).observe(root()); } catch (_) {}
  }
  setTimeout(requestHeight, 0);
  setTimeout(requestHeight, 250);
  setTimeout(ensureVisibleContent, 400);
})();`;

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(buildSandboxCsp(libraryScriptUrls))}">
<title>${title}</title>
<style>${css}</style>
${libraryScriptTags}
</head>
<body>
<main id="chatcore-artifact-root" aria-label="${title}">
${html}
</main>
<script>${shellScript}</script>
<script>
try {
${libraryGuard}${threeCompatibilityScript}${js}
} catch (error) {
  try {
    if (typeof window.__chatcoreReportArtifactError === "function") {
      window.__chatcoreReportArtifactError(String(error && error.message || error || "Artifact error"));
    } else {
      parent.postMessage({ type: "chatcore-artifact-error", message: String(error && error.message || error || "Artifact error") }, "*");
    }
  } catch (_) {}
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

// サンドボックスアーティファクトフレームのprops型定義
// Props type definition for the sandbox artifact frame
type SandboxArtifactFrameProps = {
  artifact: GenerativeUiArtifactV1;
};

// フレームの高さを最小・最大の範囲内に収める
// Clamp the frame height within the minimum and maximum range
function clampHeight(value: number) {
  if (!Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.ceil(value), MIN_FRAME_HEIGHT), MAX_FRAME_HEIGHT);
}

// 生成UIアーティファクトをサンドボックスiframe内で安全に実行・表示するコンポーネント
// Component that safely runs and displays generative UI artifacts inside a sandbox iframe
function SandboxArtifactFrameComponent({ artifact }: SandboxArtifactFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(() => clampHeight(artifact.height ?? DEFAULT_FRAME_HEIGHT) ?? DEFAULT_FRAME_HEIGHT);
  const [errorMessage, setErrorMessage] = useState("");
  const srcDoc = useMemo(() => buildSandboxArtifactSrcDoc(artifact), [artifact]);

  // アーティファクトが変わったら高さとエラーをリセットする
  // Reset height and error when the artifact changes
  useEffect(() => {
    setHeight(clampHeight(artifact.height ?? DEFAULT_FRAME_HEIGHT) ?? DEFAULT_FRAME_HEIGHT);
    setErrorMessage("");
  }, [artifact]);

  // iframeからのpostMessageで高さ変更とエラーを受け取る
  // Receive height changes and errors from the iframe via postMessage
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow || event.source !== iframeWindow) return;
      const data = event.data;
      if (!data || typeof data !== "object") return;

      if ((data as { type?: unknown }).type === "chatcore-artifact-resize") {
        const nextHeight = clampHeight((data as { height?: unknown }).height as number);
        if (nextHeight) {
          setHeight((previousHeight) => (
            Math.abs(previousHeight - nextHeight) > 1 ? nextHeight : previousHeight
          ));
        }
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

  const badgeLabel = artifact.libraries?.includes("three") ? "Generated 3D" : "Generated UI";

  return (
    <section className="sandbox-artifact" aria-label={artifact.title}>
      <header className="sandbox-artifact__header">
        <div className="sandbox-artifact__heading">
          <h3 className="sandbox-artifact__title">{artifact.title}</h3>
          {artifact.description ? (
            <p className="sandbox-artifact__description">{artifact.description}</p>
          ) : null}
        </div>
        <span className="sandbox-artifact__badge">
          <span className="sandbox-artifact__badge-dot" aria-hidden="true" />
          {badgeLabel}
        </span>
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

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const SandboxArtifactFrame = memo(SandboxArtifactFrameComponent);
SandboxArtifactFrame.displayName = "SandboxArtifactFrame";
