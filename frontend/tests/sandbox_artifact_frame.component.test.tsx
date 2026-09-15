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
});
