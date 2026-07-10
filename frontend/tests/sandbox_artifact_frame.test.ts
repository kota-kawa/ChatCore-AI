import assert from "node:assert/strict";
import test from "node:test";
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

test("SandboxArtifactFrame clamps oversized requested height", () => {
  const markup = renderToStaticMarkup(React.createElement(SandboxArtifactFrame, {
    artifact: {
      ...artifact,
      height: 1200,
    },
  }));

  assert.match(markup, /height:900px/);
});
