import { render } from "@testing-library/react";
import { useChatFooterHeight } from "../hooks/chat_page/use_chat_footer_height";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let footerHeight = 0;
let offsetHeightReads = 0;

class MockResizeObserver {
  static instances: MockResizeObserver[] = [];

  readonly observe = vi.fn();
  readonly disconnect = vi.fn();

  constructor(readonly callback: ResizeObserverCallback) {
    MockResizeObserver.instances.push(this);
  }
}

function FooterHarness({ enabled }: { enabled: boolean }) {
  const footerRef = useChatFooterHeight<HTMLDivElement>(enabled);
  return (
    <div className="chat-area">
      <div ref={footerRef} className="chat-footer" />
    </div>
  );
}

describe("useChatFooterHeight", () => {
  beforeEach(() => {
    footerHeight = 0;
    offsetHeightReads = 0;
    MockResizeObserver.instances = [];
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
      offsetHeightReads += 1;
      return this.classList.contains("chat-footer") ? footerHeight : 0;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("非表示中は計測せず、表示と復帰時に最新の高さを反映して observer を再接続する", () => {
    footerHeight = 84;
    const { container, rerender } = render(<FooterHarness enabled={false} />);
    const chatArea = container.querySelector<HTMLElement>(".chat-area");

    expect(chatArea?.style.getPropertyValue("--chat-footer-height")).toBe("");
    expect(MockResizeObserver.instances).toHaveLength(0);
    expect(offsetHeightReads).toBe(0);

    rerender(<FooterHarness enabled />);

    expect(chatArea?.style.getPropertyValue("--chat-footer-height")).toBe("84px");
    expect(MockResizeObserver.instances).toHaveLength(1);
    expect(MockResizeObserver.instances[0]?.observe).toHaveBeenCalledTimes(1);
    expect(offsetHeightReads).toBe(1);

    footerHeight = 118;
    MockResizeObserver.instances[0]?.callback([], MockResizeObserver.instances[0] as unknown as ResizeObserver);
    expect(chatArea?.style.getPropertyValue("--chat-footer-height")).toBe("118px");
    expect(offsetHeightReads).toBe(2);

    rerender(<FooterHarness enabled={false} />);
    expect(MockResizeObserver.instances[0]?.disconnect).toHaveBeenCalledTimes(1);
    expect(chatArea?.style.getPropertyValue("--chat-footer-height")).toBe("118px");
    expect(offsetHeightReads).toBe(2);

    footerHeight = 146;
    rerender(<FooterHarness enabled />);
    expect(chatArea?.style.getPropertyValue("--chat-footer-height")).toBe("146px");
    expect(MockResizeObserver.instances).toHaveLength(2);
    expect(offsetHeightReads).toBe(3);
  });
});
