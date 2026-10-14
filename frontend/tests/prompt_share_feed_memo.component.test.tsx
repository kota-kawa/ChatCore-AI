import { fireEvent, render, screen } from "@testing-library/react";
import { useMemo, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { PromptSharePageLayout } from "../components/prompt_share/prompt_share_page_layout";
import { LocaleProvider } from "../contexts/locale_context";
import type { PromptRecord } from "../components/prompt_share/prompt_card";

const mocks = vi.hoisted(() => ({ promptCardRender: vi.fn() }));

vi.mock("../components/prompt_share/prompt_card", () => ({
  PromptCard: ({ prompt }: { prompt: PromptRecord }) => {
    mocks.promptCardRender(prompt.clientId);
    return <article data-testid={`prompt-card-${prompt.clientId}`}>{prompt.title}</article>;
  }
}));

const noop = () => undefined;
const categories = [{ value: "all", label: "すべて", iconClass: "bi bi-grid" }];
const emptyIds = new Set<string>();

function PromptSharePageHarness() {
  const [searchInput, setSearchInput] = useState("");
  const [postTitle, setPostTitle] = useState("");
  const [cardTitle, setCardTitle] = useState("Original prompt");
  const visiblePrompts = useMemo<PromptRecord[]>(() => [{
    id: 1,
    clientId: "prompt-1",
    title: cardTitle,
    content: "Prompt body",
    content_format: "prompt",
    media_type: "text",
    liked: false,
    used_in_chat: false
  }], [cardTitle]);

  return (
    <PromptSharePageLayout
      authUiReady
      currentUserId={null}
      isLoggedIn
      searchInput={searchInput}
      onSearchInputChange={setSearchInput}
      onSearchInputKeyDown={noop}
      onSearch={noop}
      onOpenComposerModal={noop}
      categories={categories}
      selectedCategory="all"
      onCategoryClick={noop}
      contentFormatFilters={[]}
      selectedContentFormatFilter="all"
      onContentFormatFilterClick={noop}
      mediaTypeFilters={[]}
      selectedMediaTypeFilter="all"
      onMediaTypeFilterClick={noop}
      selectedCategoryTitle="すべてのプロンプト"
      promptCountMeta="1件"
      hasMoreResults={false}
      isLoadingMoreResults={false}
      onLoadMoreResults={noop}
      isPromptsLoading={false}
      hasPromptFeedback={false}
      visiblePrompts={visiblePrompts}
      feedbackToShow={null}
      openDropdownPromptId={null}
      likePendingIds={emptyIds}
      actionEffectIds={emptyIds}
      addAsTaskPendingIds={emptyIds}
      memoSavePendingIds={emptyIds}
      onOpenDetail={noop}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={noop}
      onEditPrompt={noop}
    >
      <label>
        投稿タイトル
        <input value={postTitle} onChange={(event) => setPostTitle(event.target.value)} />
      </label>
      <button type="button" onClick={() => setCardTitle("Updated prompt")}>更新カード</button>
    </PromptSharePageLayout>
  );
}

describe("prompt share feed render boundary", () => {
  it("keeps search and post inputs while skipping stable card work, then updates changed cards", () => {
    mocks.promptCardRender.mockClear();
    render(<LocaleProvider initialLocale="ja"><PromptSharePageHarness /></LocaleProvider>);

    expect(mocks.promptCardRender).toHaveBeenCalledTimes(1);
    fireEvent.change(document.getElementById("searchInput") as HTMLInputElement, {
      target: { value: "search text" }
    });
    fireEvent.change(screen.getByLabelText("投稿タイトル"), {
      target: { value: "post draft" }
    });

    expect(document.getElementById("searchInput")).toHaveValue("search text");
    expect(screen.getByLabelText("投稿タイトル")).toHaveValue("post draft");
    expect(mocks.promptCardRender).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "更新カード" }));

    expect(screen.getByTestId("prompt-card-prompt-1")).toHaveTextContent("Updated prompt");
    expect(mocks.promptCardRender).toHaveBeenCalledTimes(2);
  });
});
