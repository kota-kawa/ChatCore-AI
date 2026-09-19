import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SandboxArtifactFrame } from "../components/chat_page/sandbox_artifact_frame";
import type { GenerativeUiArtifactV1 } from "../lib/chat_page/types";

const ARTIFACT: GenerativeUiArtifactV1 = {
  version: 1,
  title: "Sandbox",
  description: "Local interaction only",
  height: 320,
  html: '<div id="app"></div>',
  css: "#app{padding:12px;}",
  js: "document.getElementById('app').textContent = 'ready';",
};

const RUNTIME_ERROR_TEXT = "生成UIの一部を実行できませんでした。";
const NAVIGATION_BLOCKED_TEXT = "生成UIが別のページへ移動しようとしたため、安全のため表示を停止しました。";

// iframe から親へ届く postMessage を、source 判定を満たす形で再現する。
// Replays a postMessage from the iframe in a form that satisfies the parent's source check.
function postFromIframe(data: unknown) {
  const iframe = document.querySelector("iframe");
  const event = new MessageEvent("message", { data });
  Object.defineProperty(event, "source", { value: iframe?.contentWindow });
  act(() => {
    window.dispatchEvent(event);
  });
}

// iframe要素自身のloadイベントを再現する。実ブラウザでは、srcdocの初回表示の後にもう一度
// loadが来るのは、フレーム自身が別のドキュメントへ遷移した（例: `location.href = "..."`）
// ときだけ（ヘッドレスChromiumでの実測で確認済み）。ここではjsdom上でその回数だけを
// 制御して、コンポーネント側の検出ロジック（sandbox_artifact_frame.tsx）を検証する。
// Replays the iframe element's own load event. In a real browser, a load arriving again
// after the initial srcdoc render only happens when the frame itself has navigated to a
// different document (e.g. `location.href = "..."`), confirmed against headless Chromium.
// This drives that count directly under jsdom to exercise the parent-side detection logic.
function fireIframeLoad() {
  const iframe = document.querySelector("iframe");
  if (!iframe) throw new Error("iframe not found in the current render output");
  act(() => {
    iframe.dispatchEvent(new Event("load"));
  });
}

describe("SandboxArtifactFrame", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("実行結果が届かないままならタイムアウトを知らせる", async () => {
    render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(screen.getByText(RUNTIME_ERROR_TEXT)).toBeInTheDocument();
  });

  it("描画が成功していればエラーは出さない", async () => {
    render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    postFromIframe({ type: "chatcore-artifact-status", state: "ready" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(screen.queryByText(RUNTIME_ERROR_TEXT)).toBeNull();
  });

  // ストリームはフェンス確定時と done で同じアーティファクトを二度配り、そのたびに別オブジェクトへ
  // 正規化される。中身が同じなら iframe は再読み込みされず ready は二度と来ないので、参照が変わった
  // だけで実行結果を捨てると、完走した描画が8秒後にタイムアウト扱いへ落ちてしまう。
  // The stream delivers the same artifact twice - at the closing fence and again on done - and each
  // delivery is normalized into a fresh object. An unchanged srcDoc does not reload the iframe, so a
  // ready can never arrive again; discarding the outcome on that identity change would turn a
  // finished render into a timeout eight seconds later.
  it("同じ内容のアーティファクトが再配信されても成功した実行結果を捨てない", async () => {
    const { rerender } = render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    postFromIframe({ type: "chatcore-artifact-status", state: "ready" });

    rerender(<SandboxArtifactFrame artifact={{ ...ARTIFACT }} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(screen.queryByText(RUNTIME_ERROR_TEXT)).toBeNull();
  });

  it("描画後に届いた例外では失敗表示に変えない", async () => {
    render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    postFromIframe({ type: "chatcore-artifact-status", state: "ready" });
    postFromIframe({ type: "chatcore-artifact-error", message: "click handler failed" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(screen.queryByText(RUNTIME_ERROR_TEXT)).toBeNull();
  });

  it("内容が変わったアーティファクトでは実行結果を測り直す", async () => {
    const { rerender } = render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    postFromIframe({ type: "chatcore-artifact-status", state: "ready" });

    rerender(<SandboxArtifactFrame artifact={{ ...ARTIFACT, js: "throw new Error('boom');" }} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(screen.getByText(RUNTIME_ERROR_TEXT)).toBeInTheDocument();
  });

  // sandbox="allow-scripts" は iframe 自身がトップレベル遷移すること
  // （`location.href = "..."` 等）までは止めない。allow-top-navigation は親ページを道連れに
  // する遷移だけを防ぐ属性で、フレーム自身の遷移には無関係。主たる防御は親アプリのCSPの
  // `frame-src 'self'`（frontend/next.config.mjs）で、これはナビゲーション先URLをリクエスト
  // 送出前にブロックする（実ブラウザで実測確認済み。同期・setTimeout遅延・meta refresh・
  // 204応答への繰り返し遷移のいずれも、frame-src 'self' の下ではネットワークリクエストが
  // 一切送出されずに止まる）。ここでのload イベント回数カウンタは、その防御が万一効かない
  // 場合の第二層に過ぎない。
  // sandbox="allow-scripts" does not stop the iframe from navigating itself at the top level
  // (e.g. `location.href = "..."`) - allow-top-navigation only guards the *parent* page from
  // being dragged along, not the frame's own navigation. The primary defense is the parent
  // app's CSP `frame-src 'self'` (frontend/next.config.mjs), which blocks the navigation target
  // before any request is sent (confirmed against a real browser: synchronous, setTimeout-
  // deferred, meta-refresh, and repeated navigations to a 204 endpoint are all blocked with zero
  // network requests under frame-src 'self'). The load-event counter tested below is only a
  // second layer for when that primary defense is somehow unavailable.
  //
  // 既知の制約: このテストは「初回のsrcdocロードでは遮断しない」ことを検証するが、これは
  // 同時に「1回しかloadが来ない状況を区別できない」ことも意味する。攻撃者JSが解析中に
  // 同期的に `location.href = ...` を代入した場合、元のsrcdocのloadは発火せず遷移後
  // （または失敗後）のドキュメントのloadだけが1回だけ来るため、このカウンタ単体では
  // 検出できない。frame-src 'self' が主防御である理由はここにある。
  // Known limitation: this test verifies the first load after srcdoc is not treated as a
  // navigation, but that also means a situation where exactly one load arrives is
  // indistinguishable from an attack. If the artifact's JS assigns `location.href = ...`
  // synchronously while the document is still parsing, the original srcdoc's load never fires
  // and only the navigated-to (or failed) document's load arrives - exactly once - so this
  // counter alone cannot detect it. This is why frame-src 'self' is the primary defense.
  it("srcdocの初回ロードでは遮断しない", () => {
    render(<SandboxArtifactFrame artifact={ARTIFACT} />);

    fireIframeLoad();

    expect(document.querySelector("iframe")).not.toBeNull();
    expect(screen.queryByText(NAVIGATION_BLOCKED_TEXT)).toBeNull();
  });

  it("srcdoc設定後の想定外の2回目のloadを遷移とみなしフレームを破棄する", () => {
    render(<SandboxArtifactFrame artifact={ARTIFACT} />);

    fireIframeLoad(); // 初回表示（無視されるべき）
    fireIframeLoad(); // アーティファクト内JSがlocationで遷移した想定

    // iframeそのものをDOMから外し、中で動いていたスクリプトを止める。
    // Removes the iframe from the DOM, stopping whatever script was still running inside it.
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.getByText(NAVIGATION_BLOCKED_TEXT)).toBeInTheDocument();
  });

  it("遷移検出後に新しいアーティファクトが届けばフレーム表示へ復帰する", () => {
    const { rerender } = render(<SandboxArtifactFrame artifact={ARTIFACT} />);
    fireIframeLoad();
    fireIframeLoad();
    expect(screen.getByText(NAVIGATION_BLOCKED_TEXT)).toBeInTheDocument();

    rerender(
      <SandboxArtifactFrame
        artifact={{ ...ARTIFACT, js: "document.getElementById('app').textContent = 'again';" }}
      />
    );

    expect(document.querySelector("iframe")).not.toBeNull();
    expect(screen.queryByText(NAVIGATION_BLOCKED_TEXT)).toBeNull();
  });
});
