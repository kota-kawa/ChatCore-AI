import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  buildSandboxArtifactSrcDoc,
  SandboxArtifactFrame,
} from "../components/chat_page/sandbox_artifact_frame";
import type { GenerativeUiArtifactV1 } from "../lib/chat_page/types";

const artifact: GenerativeUiArtifactV1 = {
  version: 1,
  title: "Sandbox",
  description: "Local interaction only",
  height: 320,
  html: '<div id="app"></div>',
  css: "#app{padding:12px;}",
  js: "document.getElementById('app').textContent = 'ready';",
};

test("SandboxArtifactFrame renders a script-only sandbox iframe", () => {
  const markup = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, { artifact }));

  assert.match(markup, /sandbox="allow-scripts"/);
  assert.doesNotMatch(markup, /allow-same-origin/);
  assert.match(markup, /referrerPolicy="no-referrer"|referrerpolicy="no-referrer"/);
});

test("SandboxArtifactFrame leaves srcDoc out of the server-rendered markup", () => {
  // srcDoc の CSP は window.location.origin に依存するためサーバーでは組み立てられない。
  // SSR 時点で srcDoc を出すとハイドレーション不一致になるので、マウント後に流し込む。
  // The srcDoc CSP depends on window.location.origin, so it cannot be built on the server.
  // Emitting it during SSR would break hydration; it is injected after mount instead.
  const markup = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, { artifact }));

  assert.doesNotMatch(markup, /srcdoc=/i);
  assert.match(markup, /<iframe/);
});

test("buildSandboxArtifactSrcDoc includes restrictive CSP and escapes script endings", () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    js: "document.body.dataset.value = '</script>';",
  });

  assert.match(srcDoc, /default-src 'none'/);
  assert.match(srcDoc, /connect-src 'none'/);
  assert.match(srcDoc, /form-action 'none'/);
  assert.doesNotMatch(srcDoc, /document\.body\.dataset\.value = '<\/script>';$/);
  assert.match(srcDoc, /<\\\/script>/);
});

test("buildSandboxArtifactSrcDoc wraps generated markup in a stable root shell", () => {
  const srcDoc = buildSandboxArtifactSrcDoc(artifact);

  assert.match(srcDoc, /id="chatcore-artifact-root"/);
  assert.match(srcDoc, /__chatcoreReportArtifactError/);
  assert.match(srcDoc, /MAX_HEIGHT = 900/);
  assert.match(srcDoc, /ResizeObserver/);
});

test("buildSandboxArtifactSrcDoc includes an empty-artifact fallback", () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    html: "",
    js: "",
  });

  assert.match(srcDoc, /chatcore-empty-artifact/);
  assert.match(srcDoc, /__chatcoreEnsureArtifactVisible/);
  assert.doesNotMatch(srcDoc, /rect\.width > 2 && rect\.height > 2\) return true/);
  assert.match(srcDoc, /hasBackground \|\| hasBorder \|\| style\.boxShadow/);
  assert.match(srcDoc, /firstErrorMessage && !readyReported/);
  assert.match(srcDoc, /node\.closest\("#chatcore-empty-artifact"\)/);
});

test("sandbox keeps the safe fallback visible after a runtime error", async () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    js: `
      const app = document.getElementById("app");
      app.style.backgroundColor = "red";
      app.getBoundingClientRect = () => ({ width: 500, height: 300 });
      throw new Error("render failed");
    `,
  });
  const dom = new JSDOM(srcDoc, { pretendToBeVisual: true, runScripts: "dangerously" });

  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.ok(dom.window.document.getElementById("chatcore-empty-artifact"));
  dom.window.close();
});

// iframe が親へ送った postMessage を集める。実行結果の判定はこのメッセージだけで決まる。
// Collects the postMessage traffic the iframe sends to its parent: the verdict travels only here.
async function collectSandboxMessages(
  srcDoc: string,
  waitMs: number,
  during?: (win: Window & typeof globalThis) => void,
) {
  const dom = new JSDOM(srcDoc, { pretendToBeVisual: true, runScripts: "dangerously" });
  const win = dom.window as unknown as Window & typeof globalThis;
  const received: Array<{ type?: string; state?: string; message?: string }> = [];
  win.addEventListener("message", (event: MessageEvent) => {
    received.push(event.data as { type?: string; state?: string; message?: string });
  });
  if (during) during(win);
  await new Promise((resolve) => setTimeout(resolve, waitMs));
  const statuses = received.filter((entry) => entry?.type === "chatcore-artifact-status");
  const errors = received.filter((entry) => entry?.type === "chatcore-artifact-error");
  dom.window.close();
  return { statuses, errors };
}

test("an exception after the UI rendered never reports a failure", async () => {
  // クリックハンドラの失敗などは、表示されているUIを失敗扱いにしてはいけない。
  // A failing click handler must not condemn a UI that is on screen.
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    js: `
      document.getElementById("app").textContent = "rendered";
      setTimeout(function(){ throw new Error("late failure"); }, 560);
    `,
  });

  const { statuses, errors } = await collectSandboxMessages(srcDoc, 750);

  assert.deepEqual(statuses.map((entry) => entry.state), ["ready"]);
  assert.ok(errors.length >= 1, "診断用のエラー通知は残る / the diagnostic error is still delivered");
});

test("a CSP block that did not stop the render reports ready", async () => {
  // フォントやメディアの遮断は描画を止めない。赤い警告を出す理由にはならない。
  // A blocked font or media file does not stop the render, so it is no reason to warn.
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    js: 'document.getElementById("app").textContent = "rendered";',
  });

  const { statuses } = await collectSandboxMessages(srcDoc, 750, (win) => {
    const event = new win.Event("securitypolicyviolation");
    Object.defineProperty(event, "violatedDirective", { value: "font-src" });
    win.document.dispatchEvent(event);
  });

  assert.deepEqual(statuses.map((entry) => entry.state), ["ready"]);
});

test("a CSP block that left the frame empty still reports csp_blocked", async () => {
  const srcDoc = buildSandboxArtifactSrcDoc({ ...artifact, html: "", css: "", js: "" });

  const { statuses } = await collectSandboxMessages(srcDoc, 750, (win) => {
    const event = new win.Event("securitypolicyviolation");
    Object.defineProperty(event, "violatedDirective", { value: "script-src" });
    win.document.dispatchEvent(event);
  });

  assert.deepEqual(statuses.map((entry) => entry.state), ["csp_blocked"]);
  assert.equal(statuses[0]?.message, "script-src");
});

test("a failed run with nothing on screen still reports runtime_error", async () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    css: "",
    js: 'throw new Error("render failed");',
  });

  const { statuses } = await collectSandboxMessages(srcDoc, 750);

  assert.deepEqual(statuses.map((entry) => entry.state), ["runtime_error"]);
  assert.match(String(statuses[0]?.message), /render failed/);
});

test("buildSandboxArtifactSrcDoc injects local three.js when the artifact requests it", () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    libraries: ["three"],
    js: "const scene = new THREE.Scene();",
  });

  assert.match(srcDoc, /<script src="[^"]*\/static\/js\/vendor\/three\.min\.js"><\/script>/);
  assert.match(srcDoc, /script-src 'unsafe-inline' [^;]*\/static\/js\/vendor\/three\.min\.js/);
  assert.match(srcDoc, /typeof THREE === "undefined"/);
  assert.match(srcDoc, /default-src 'none'/);
  assert.match(srcDoc, /connect-src 'none'/);
});

test("buildSandboxArtifactSrcDoc keeps plain artifacts free of library scripts", () => {
  const srcDoc = buildSandboxArtifactSrcDoc(artifact);

  assert.doesNotMatch(srcDoc, /three\.min\.js/);
  assert.doesNotMatch(srcDoc, /typeof THREE/);
  assert.match(srcDoc, /script-src 'unsafe-inline';/);
});

test("buildSandboxArtifactSrcDoc supplies local OrbitControls compatibility", () => {
  const srcDoc = buildSandboxArtifactSrcDoc({
    ...artifact,
    libraries: ["three"],
    js: "const controls = new OrbitControls(camera, renderer.domElement); controls.update();",
  });

  assert.match(srcDoc, /function OrbitControls\(camera, element\)/);
  assert.match(srcDoc, /THREE\.OrbitControls=OrbitControls/);
  assert.doesNotMatch(srcDoc, /three\/examples\/jsm\/controls/);
});

test("SandboxArtifactFrame shows a badge reflecting the artifact type", () => {
  const markup2d = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, { artifact }));
  assert.match(markup2d, /sandbox-artifact__badge/);
  assert.match(markup2d, /Generated UI/);

  const markup3d = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, {
    artifact: {
      ...artifact,
      libraries: ["three"],
      js: "const scene = new THREE.Scene();",
    },
  }));
  assert.match(markup3d, /Generated 3D/);
});

test("SandboxArtifactFrame clamps oversized requested height", () => {
  const markup = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, {
    artifact: {
      ...artifact,
      height: 1200,
    },
  }));

  assert.match(markup, /height:900px/);
});

// 実行時の成否は、サーバー検証では観測できない。iframe から必ず結果が返ることを固定する。
// The runtime outcome is invisible to server-side validation, so the iframe must always report it.
async function collectArtifactStatus(srcDoc: string, waitMs: number) {
  const dom = new JSDOM(srcDoc, { pretendToBeVisual: true, runScripts: "dangerously" });
  const states: string[] = [];
  const listener = (event: MessageEvent) => {
    const data = event.data as { type?: string; state?: string } | null;
    if (data && data.type === "chatcore-artifact-status" && typeof data.state === "string") {
      states.push(data.state);
    }
  };
  (dom.window as unknown as Window).addEventListener("message", listener as EventListener);

  await new Promise((resolve) => setTimeout(resolve, waitMs));
  dom.window.close();
  return states;
}

test("sandbox reports a blank render instead of looking successful", async () => {
  const states = await collectArtifactStatus(
    buildSandboxArtifactSrcDoc({ ...artifact, html: "", js: "" }),
    650,
  );

  assert.deepEqual(states, ["blank"]);
});

test("sandbox reports a thrown runtime error", async () => {
  const states = await collectArtifactStatus(
    buildSandboxArtifactSrcDoc({ ...artifact, js: 'throw new Error("render failed");' }),
    650,
  );

  assert.deepEqual(states, ["runtime_error"]);
});

test("sandbox reports a successful render exactly once", async () => {
  const states = await collectArtifactStatus(buildSandboxArtifactSrcDoc(artifact), 650);

  assert.deepEqual(states, ["ready"]);
});

test("sandbox listens for rejected promises and CSP violations, not only sync errors", () => {
  const srcDoc = buildSandboxArtifactSrcDoc(artifact);

  assert.match(srcDoc, /addEventListener\("unhandledrejection"/);
  assert.match(srcDoc, /addEventListener\("securitypolicyviolation"/);
  assert.match(srcDoc, /csp_blocked/);
});
