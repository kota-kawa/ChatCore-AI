import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { MemoToolbar } from "../components/memo/MemoToolbar";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

function ToolbarHarness() {
  const [archiveScope, setArchiveScope] = useState("active");
  const [sortMode, setSortMode] = useState("manual");
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);
  const [isCollectionPanelOpen, setIsCollectionPanelOpen] = useState(false);

  const controller = createMemoPageControllerStub({
    archiveScope,
    setArchiveScope,
    sortMode,
    setSortMode,
    activeCollectionId,
    setActiveCollectionId,
    isFiltersOpen,
    setIsFiltersOpen,
    setIsCollectionPanelOpen,
    collections: [{ id: 1, name: "仕事", color: "#3b82f6", memo_count: 2 }],
    totalMemoCount: 2,
    hasActiveFilters: archiveScope !== "active" || sortMode !== "manual" || activeCollectionId !== null,
  });

  return (
    <MemoPageContextProvider controller={controller}>
      <MemoToolbar />
      <output data-testid="toolbar-state">
        {`${archiveScope}/${sortMode}/${activeCollectionId ?? "all"}/${isCollectionPanelOpen}`}
      </output>
    </MemoPageContextProvider>
  );
}

describe("MemoToolbar mobile controls", () => {
  it("provides the sidebar filtering and collection-management actions", () => {
    render(<ToolbarHarness />);

    fireEvent.click(screen.getByRole("button", { name: "表示・整理メニュー" }));
    expect(screen.getByRole("region", { name: "メモの表示・整理" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "アーカイブ" }));
    expect(screen.getByTestId("toolbar-state")).toHaveTextContent("archived/manual/all/false");

    fireEvent.click(screen.getByRole("button", { name: "並び順" }));
    fireEvent.click(screen.getByRole("option", { name: "タイトル順" }));
    expect(screen.getByTestId("toolbar-state")).toHaveTextContent("archived/title/all/false");

    fireEvent.click(screen.getByRole("button", { name: "コレクション" }));
    fireEvent.click(screen.getByRole("option", { name: "仕事" }));
    expect(screen.getByTestId("toolbar-state")).toHaveTextContent("archived/title/1/false");

    fireEvent.click(screen.getByRole("button", { name: "コレクションを管理" }));
    expect(screen.getByTestId("toolbar-state")).toHaveTextContent("archived/title/1/true");
  });
});

describe("MemoToolbar in the trash", () => {
  it("offers a Trash chip next to All memos and Archive that switches the scope", () => {
    render(<ToolbarHarness />);
    fireEvent.click(screen.getByRole("button", { name: "表示・整理メニュー" }));

    fireEvent.click(screen.getByRole("button", { name: "ゴミ箱" }));

    expect(screen.getByTestId("toolbar-state")).toHaveTextContent("trash/manual/all/false");
    expect(screen.getByRole("heading", { level: 2, name: "ゴミ箱" })).toBeInTheDocument();
  });

  it("drops the export button there, because exports never include trashed memos", () => {
    render(<ToolbarHarness />);
    expect(screen.getByRole("button", { name: "エクスポート" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "表示・整理メニュー" }));
    fireEvent.click(screen.getByRole("button", { name: "ゴミ箱" }));

    expect(screen.queryByRole("button", { name: "エクスポート" })).toBeNull();
  });
});
