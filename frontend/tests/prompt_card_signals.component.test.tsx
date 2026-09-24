import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";

const noop = () => {};

const basePrompt: PromptRecord = {
  id: 7,
  clientId: "prompt-7",
  title: "設計レビューの観点を洗い出す",
  content: "設計ドキュメントを受け取り、レビュー観点を列挙してください。",
  category: "coding",
  author: "Kota",
  content_format: "prompt",
  media_type: "text",
  liked: false,
  used_in_chat: false,
  comment_count: 0,
  created_at: "2026-06-01T00:00:00Z"
};

function renderCard(overrides: Partial<PromptRecord> = {}, onImpression?: (prompt: PromptRecord) => void) {
  return render(
    <PromptCard
      prompt={{ ...basePrompt, ...overrides }}
      isDropdownOpen={false}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isMemoSavePending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={noop}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
      onImpression={onImpression}
    />
  );
}

// jsdom には IntersectionObserver が無い。観測開始で即「見えた」と通知する代用品を差し込む。
// jsdom lacks IntersectionObserver; this stand-in reports the element as visible as soon as it is observed.
class VisibleImmediatelyObserver {
  static instances: VisibleImmediatelyObserver[] = [];
  disconnected = false;
  constructor(private readonly callback: IntersectionObserverCallback) {
    VisibleImmediatelyObserver.instances.push(this);
  }
  observe(target: Element) {
    this.callback(
      [{ isIntersecting: true, target } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver
    );
  }
  disconnect() {
    this.disconnected = true;
  }
  unobserve() {}
  takeRecords() {
    return [];
  }
}

describe("PromptCard signals", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    VisibleImmediatelyObserver.instances = [];
  });

  it("shows the view count and the like count", () => {
    renderCard({ view_count: 128, like_count: 5 });

    expect(screen.getByLabelText("閲覧 128 回")).toHaveTextContent("128");
    expect(screen.getByLabelText("いいね 5 件")).toHaveTextContent("5");
  });

  it("hides the like count while nobody has liked the prompt", () => {
    renderCard({ view_count: 0, like_count: 0 });

    expect(screen.getByLabelText("閲覧 0 回")).toBeInTheDocument();
    expect(screen.queryByLabelText(/いいね \d+ 件/)).toBeNull();
  });

  it("marks operator-featured prompts with a staff pick badge", () => {
    renderCard({ featured_at: "2026-09-24T00:00:00" });
    expect(screen.getByText("運営ピック")).toBeInTheDocument();

    renderCard({ featured_at: null, title: "ふつうの投稿" });
    expect(screen.getAllByText("運営ピック")).toHaveLength(1);
  });

  it("reports one impression once the card becomes visible and stops observing", () => {
    vi.stubGlobal("IntersectionObserver", VisibleImmediatelyObserver);
    const onImpression = vi.fn();

    renderCard({}, onImpression);

    expect(onImpression).toHaveBeenCalledTimes(1);
    expect(onImpression.mock.calls[0][0].id).toBe(7);
    expect(VisibleImmediatelyObserver.instances[0].disconnected).toBe(true);
  });

  it("renders without an observer when the browser lacks IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const onImpression = vi.fn();

    renderCard({}, onImpression);

    expect(onImpression).not.toHaveBeenCalled();
  });
});
