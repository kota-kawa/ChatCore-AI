import React, { memo, useEffect, useMemo, useRef, useState } from "react";

import type { GenerativeUiArtifactV1, SandboxArtifactRuntimeState } from "../../lib/chat_page/types";
import { useTranslation } from "../../contexts/locale_context";

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
// 実行結果を確定させるまでの待ち時間。サーバー検証を通っても、ブラウザでは空表示や
// 例外で何も出ないことがあるため、iframe から必ず結果を受け取る。
// How long to wait before the runtime outcome is settled. Server-side validation cannot see a
// blank render or a thrown error, so the iframe always reports what actually happened.
const RUNTIME_STATUS_DELAY_MS = 500;
const RUNTIME_STATUS_TIMEOUT_MS = 8000;

// サンドボックス内に適用するベースCSSリセット
// iframe は別ドキュメントなので _app.tsx の base/form_zoom_guard.css は届かない。生成UIが
// 16px 未満の入力欄を出すとタップで親ページごとズームするため、同じ下限をここにも持たせる。
// このリセットはアーティファクトのCSSより前に連結されるので !important が要る。
// Base CSS reset applied inside the sandbox. The iframe is a separate document, so
// base/form_zoom_guard.css from _app.tsx never reaches it; a generated control under 16px would
// zoom the whole parent page on tap, so the same floor is repeated here. This reset is
// concatenated before the artifact's own CSS, which is why it needs !important.
const BASE_SANDBOX_CSS = `
html,body{margin:0;min-height:100%;background:transparent;color:#111827;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere;}
*{box-sizing:border-box;}
img,svg,canvas,video{max-width:100%;height:auto;}
table{max-width:100%;border-collapse:collapse;}
pre{max-width:100%;overflow:auto;}
button,input,select,textarea{font:inherit;}
button{cursor:pointer;}
@media (pointer:coarse){input:not([type="checkbox"],[type="radio"],[type="range"],[type="color"],[type="submit"],[type="button"],[type="reset"],[type="file"]),textarea,select{font-size:max(16px,1em)!important;}}
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
export function buildSandboxArtifactSrcDoc(artifact: GenerativeUiArtifactV1, english = false) {
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
  var statusReported = false;
  var readyReported = false;
  var firstErrorMessage = "";
  var cspViolation = "";
  // 描画の証拠の強さ。文字・図形・操作要素は確かな証拠、背景や枠だけの箱は弱い証拠として扱う。
  // 弱い証拠は、色のついた空箱を成功と読み違えないために例外が起きたときだけ格下げする。
  // How strong the evidence of a render is. Text, graphics, and controls are solid evidence; a box
  // with only a background or border is weak, and weak evidence is discounted when something threw
  // so that a coloured empty box is never mistaken for a result.
  var EVIDENCE_NONE = 0;
  var EVIDENCE_WEAK = 1;
  var EVIDENCE_STRONG = 2;
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
  function contentEvidence(){
    var container = root();
    if (!container) return EVIDENCE_NONE;
    var nodes = container.querySelectorAll ? container.querySelectorAll("*") : (container.children || []);
    var weak = false;
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.id === "chatcore-empty-artifact" || (node.closest && node.closest("#chatcore-empty-artifact"))) continue;
      var tag = String(node.tagName || "").toLowerCase();
      if (tag === "script" || tag === "style") continue;
      if (/^(canvas|svg|img|video|button|input|select|textarea)$/.test(tag)) return EVIDENCE_STRONG;
      if (node.querySelector && node.querySelector("canvas,svg,img,video,button,input,select,textarea")) return EVIDENCE_STRONG;
      if (String(node.textContent || "").trim()) return EVIDENCE_STRONG;
      // 空の #app もCSSによって寸法を持つことがあるため、寸法だけでは描画成功と判定しない。
      // An empty #app can have dimensions from CSS, so geometry alone is not
      // evidence of a successful render.
      var rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
      var style = typeof getComputedStyle === "function" ? getComputedStyle(node) : null;
      if (rect && rect.width > 2 && rect.height > 2 && style) {
        var backgroundColor = String(style.backgroundColor || "").toLowerCase().split(" ").join("");
        var hasBackground = style.backgroundImage !== "none" || (
          backgroundColor !== "" &&
          backgroundColor !== "transparent" &&
          backgroundColor !== "rgba(0,0,0,0)" &&
          backgroundColor !== "rgb(0,0,0,0)"
        );
        var hasBorder = [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth]
          .some(function(width){ return parseFloat(width || "0") > 0; });
        if (hasBackground || hasBorder || style.boxShadow !== "none") weak = true;
      }
    }
    return weak ? EVIDENCE_WEAK : EVIDENCE_NONE;
  }
  function ensureVisibleContent(){
    // 例外が起きた直後は、色や枠だけの空箱を描画成功と見なさない。ただし一度 ready を報告した
    // あとは、クリック時の例外で完成した表示を空扱いに落とさない。
    // Right after an exception a box with only colour or a border does not count as a render, but
    // once ready has been reported a later click-time exception never demotes a finished display.
    var evidence = contentEvidence();
    var rendered = (firstErrorMessage && !readyReported)
      ? evidence === EVIDENCE_STRONG
      : evidence !== EVIDENCE_NONE;
    if (rendered) {
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
      title.textContent = ${JSON.stringify(english ? "Displaying generated UI" : "生成UIを表示しています")};
      var note = document.createElement("span");
      note.textContent = ${JSON.stringify(english ? "The model returned no visible content, so a safe display area was added." : "モデル出力が空だったため、安全な表示領域を補完しました。")};
      fallback.appendChild(title);
      fallback.appendChild(note);
      root().appendChild(fallback);
    }
    requestHeight();
  }
  function reportStatus(state, message){
    // 結果は一度だけ確定させる。確定後に届く例外は結論を塗り替えない。
    // The outcome is settled once; a later exception never rewrites that conclusion.
    if (statusReported) return;
    statusReported = true;
    readyReported = state === "ready";
    send("chatcore-artifact-status", {
      state: state,
      message: String(message || "").slice(0, 180)
    });
  }
  // 例外はその場では失敗と決めない。描画されているUIをボタン1つの例外で「実行できません
  // でした」に落とすのが誤検知の元だったため、理由だけ控えて判定チェックポイントへ回す。
  // 親のコンソールには常に流すので、診断の手掛かりは失われない。
  // An exception is not a verdict on its own. Condemning a UI that did render because one
  // handler threw was the source of the false alarm, so the reason is only recorded and the
  // verdict is left to the checkpoint. The parent console still receives every one of them.
  function reportError(message){
    var text = String(message || "Artifact script error");
    if (!firstErrorMessage) firstErrorMessage = text;
    send("chatcore-artifact-error", { message: text });
    setTimeout(ensureVisibleContent, 0);
  }
  // 実行結果は「実際に何か描画されたか」で決める。フォントやメディアの遮断のように、
  // 描画を止めない失敗まで赤い警告にしない。
  // The outcome is decided by whether anything actually rendered, so failures that do not
  // stop the render - a blocked font or media file - never raise the red warning.
  function reportRuntimeOutcome(){
    if (statusReported) return;
    var evidence = contentEvidence();
    var failed = firstErrorMessage || cspViolation;
    if (evidence === EVIDENCE_STRONG || (evidence === EVIDENCE_WEAK && !failed)) {
      reportStatus("ready", "");
      return;
    }
    if (cspViolation) {
      reportStatus("csp_blocked", cspViolation);
      return;
    }
    if (firstErrorMessage) {
      reportStatus("runtime_error", firstErrorMessage);
      return;
    }
    reportStatus("blank", "");
  }
  window.__chatcoreEnsureArtifactVisible = ensureVisibleContent;
  window.__chatcoreReportArtifactError = reportError;
  window.addEventListener("load", requestHeight);
  window.addEventListener("error", function(event){
    reportError(event.message);
  });
  // 同期例外だけでは Promise 内の失敗と CSP 遮断を取りこぼす。
  // Synchronous errors alone miss failures inside promises and CSP blocks.
  window.addEventListener("unhandledrejection", function(event){
    var reason = event && event.reason;
    reportError((reason && reason.message) || reason || "Unhandled promise rejection");
  });
  document.addEventListener("securitypolicyviolation", function(event){
    if (!cspViolation) cspViolation = String((event && event.violatedDirective) || "csp");
  });
  if (typeof ResizeObserver === "function") {
    try { new ResizeObserver(requestHeight).observe(document.documentElement); } catch (_) {}
    try { new ResizeObserver(requestHeight).observe(root()); } catch (_) {}
  }
  setTimeout(requestHeight, 0);
  setTimeout(requestHeight, 250);
  setTimeout(ensureVisibleContent, 400);
  setTimeout(reportRuntimeOutcome, ${RUNTIME_STATUS_DELAY_MS});
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
const RUNTIME_STATES = new Set<SandboxArtifactRuntimeState>([
  "ready",
  "blank",
  "runtime_error",
  "csp_blocked",
  "timeout",
]);

function clampHeight(value: number) {
  if (!Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.ceil(value), MIN_FRAME_HEIGHT), MAX_FRAME_HEIGHT);
}

// 生成UIアーティファクトをサンドボックスiframe内で安全に実行・表示するコンポーネント
// Component that safely runs and displays generative UI artifacts inside a sandbox iframe
function SandboxArtifactFrameComponent({ artifact }: SandboxArtifactFrameProps) {
  const { locale, t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(() => clampHeight(artifact.height ?? DEFAULT_FRAME_HEIGHT) ?? DEFAULT_FRAME_HEIGHT);
  const [runtimeState, setRuntimeState] = useState<SandboxArtifactRuntimeState | "">("");
  // srcDoc の CSP には自オリジンの絶対URL（window.location.origin）が必要なため、
  // サーバーでは組み立てられない。SSR とハイドレーション初回は srcDoc を付けず、
  // マウント後に流し込むことでハイドレーション不一致と不正なCSPソースを避ける。
  // The srcDoc CSP needs same-origin absolute URLs (window.location.origin), which the
  // server cannot produce. Render without srcDoc during SSR and the first hydration
  // render, then inject it after mount to avoid both a hydration mismatch and an
  // invalid CSP source.
  const [isMounted, setIsMounted] = useState(false);
  useEffect(() => {
    setIsMounted(true);
  }, []);
  const srcDoc = useMemo(
    () => (isMounted ? buildSandboxArtifactSrcDoc(artifact, locale === "en") : undefined),
    [artifact, isMounted, locale]
  );

  // 高さのリセットは指定値が変わったときだけ。同じ内容の再配信で iframe が実測した高さを
  // 捨てると、正しく伸びていた表示が既定値へ縮む。
  // Reset the height only when the requested value changes; dropping the height the iframe
  // measured on an identical re-delivery would shrink a correctly grown frame back to default.
  useEffect(() => {
    setHeight(clampHeight(artifact.height ?? DEFAULT_FRAME_HEIGHT) ?? DEFAULT_FRAME_HEIGHT);
  }, [artifact.height]);

  // 実行結果を捨てるのは srcDoc（iframe に実際に流し込む内容）が変わったときだけにする。
  // ストリームはフェンス確定時と done で同じアーティファクトを二度配るため、毎回 normalize
  // された別オブジェクトが届く。参照が変わっただけでリセットすると、内容が同じ srcDoc では
  // iframe が再読み込みされず ready が二度と来ないので、完走した描画がタイムアウト扱いになる。
  // Only a change of srcDoc - what the iframe actually runs - discards the outcome. The stream
  // delivers the same artifact twice (at the closing fence and again on done) and each delivery
  // is normalized into a fresh object. Resetting on that identity change would clear a ready
  // that can never arrive again, because an unchanged srcDoc does not reload the iframe, and the
  // finished render would then be reported as a timeout.
  useEffect(() => {
    setRuntimeState("");
  }, [srcDoc]);

  // 結果が何も届かないまま止まった場合もタイムアウトとして扱う。無言のままにしない。
  // 結果が確定したらタイマーは畳む（古いタイマーが後から発火して結果を奪わないように）。
  // A run that reports nothing at all is a timeout, not a silent success. The timer is torn down
  // as soon as the outcome is known so a stale one cannot fire later and steal the verdict.
  useEffect(() => {
    if (!srcDoc || runtimeState !== "") return undefined;
    const timer = window.setTimeout(() => {
      setRuntimeState((previous) => (previous ? previous : "timeout"));
    }, RUNTIME_STATUS_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [runtimeState, srcDoc]);

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

      // 例外は診断用に残すだけ。表示するかどうかは iframe が返す実行結果だけで決める。
      // An exception is kept for diagnostics only; the banner is driven by the reported outcome.
      if ((data as { type?: unknown }).type === "chatcore-artifact-error") {
        const message = (data as { message?: unknown }).message;
        const normalizedMessage = typeof message === "string" ? message.slice(0, 180) : "Artifact error";
        console.warn(`Generated UI runtime error (${artifact.title}): ${normalizedMessage}`);
        return;
      }

      if ((data as { type?: unknown }).type === "chatcore-artifact-status") {
        const state = (data as { state?: unknown }).state;
        if (typeof state === "string" && RUNTIME_STATES.has(state as SandboxArtifactRuntimeState)) {
          setRuntimeState(state as SandboxArtifactRuntimeState);
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [artifact.title]);

  const badgeLabel = artifact.libraries?.includes("three") ? "Generated 3D" : "Generated UI";
  // 例外・CSP遮断・タイムアウトは同じ「実行できなかった」、空表示だけは別の文言で伝える。
  // A thrown error, a CSP block, and a timeout share one message; a blank render gets its own.
  const runtimeFailed = runtimeState !== "" && runtimeState !== "ready";
  const runtimeMessage = runtimeState === "blank"
    ? t("chat.generatedUiBlank")
    : (runtimeFailed ? t("chat.generatedUiError") : "");

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
      {runtimeMessage ? (
        <p className="sandbox-artifact__error" data-runtime-state={runtimeState}>
          {runtimeMessage}
        </p>
      ) : null}
    </section>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const SandboxArtifactFrame = memo(SandboxArtifactFrameComponent);
SandboxArtifactFrame.displayName = "SandboxArtifactFrame";
