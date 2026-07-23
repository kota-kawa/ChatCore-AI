import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import { MyContextPanel } from "../components/memo/MyContextPanel";
import type { ContextFact } from "../lib/memo/context_types";

function renderPanel(props: Parameters<typeof MyContextPanel>[0]) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MyContextPanel {...props} />
    </SWRConfig>,
  );
}

const sampleFact: ContextFact = {
  id: 3,
  fact_type: "preference",
  title: "エディタの好み",
  content: "vim キーバインドを使う",
  source_kind: "manual",
  importance: 75,
  status: "active",
  revision: 2,
  created_at: null,
  updated_at: null,
};

const projectFact: ContextFact = {
  ...sampleFact,
  id: 4,
  fact_type: "project",
  title: "進行中の刷新プロジェクト",
  content: "API互換性を維持して段階移行する",
  revision: 1,
};

describe("MyContextPanel", () => {
  it("shows a login prompt when logged out and does not fetch", () => {
    const load = vi.fn();
    renderPanel({ isLoggedIn: false, api: { load } });

    expect(screen.getByText(/ログインすると利用できます/)).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("lists facts returned by the API", async () => {
    const load = vi.fn().mockResolvedValue({
      facts: [sampleFact],
      totalActive: 1,
      nextCursor: null,
    });
    renderPanel({ isLoggedIn: true, api: { load } });

    await waitFor(() => expect(screen.getByText("エディタの好み")).toBeInTheDocument());
    expect(screen.getByText("出典: 手動")).toBeInTheDocument();
    expect(screen.getByText("重要度: 高")).toBeInTheDocument();
    expect(load).toHaveBeenCalledWith({ factType: null, status: "active" });
  });

  it("creates a fact through the editor and reloads", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ facts: [], totalActive: 0, nextCursor: null })
      .mockResolvedValue({ facts: [sampleFact], totalActive: 1, nextCursor: null });
    const create = vi.fn().mockResolvedValue(sampleFact);
    renderPanel({ isLoggedIn: true, api: { load, create } });

    fireEvent.click(screen.getByRole("button", { name: /コンテキストを追加/ }));
    expect(screen.getByRole("dialog", { name: "コンテキストを追加" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.change(screen.getByLabelText("タイトル"), {
      target: { value: "エディタの好み" },
    });
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "vim キーバインドを使う" },
    });
    fireEvent.click(screen.getByRole("button", { name: "重要度" }));
    fireEvent.click(screen.getByRole("option", { name: "高" }));
    fireEvent.click(screen.getByRole("button", { name: "追加" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        fact_type: "preference",
        title: "エディタの好み",
        content: "vim キーバインドを使う",
        importance: 75,
      }),
    );
  });

  it("closes the accessible editor modal with Escape and restores body scrolling", async () => {
    const load = vi.fn().mockResolvedValue({ facts: [], totalActive: 0, nextCursor: null });
    renderPanel({ isLoggedIn: true, api: { load } });

    fireEvent.click(screen.getByRole("button", { name: /コンテキストを追加/ }));
    expect(screen.getByRole("dialog", { name: "コンテキストを追加" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "コンテキストを追加" })).not.toBeInTheDocument();
      expect(document.body.style.overflow).toBe("");
    });
  });

  it("loads subsequent cursor pages with the active filters and removes duplicate facts", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ facts: [sampleFact], totalActive: 2, nextCursor: "cursor-1" })
      .mockResolvedValueOnce({
        facts: [sampleFact, projectFact, projectFact],
        totalActive: 2,
        nextCursor: null,
      });
    renderPanel({ isLoggedIn: true, api: { load } });

    await waitFor(() => expect(screen.getByRole("button", { name: "さらに読み込む" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "さらに読み込む" }));

    await waitFor(() => expect(screen.getByText(projectFact.title)).toBeInTheDocument());
    expect(screen.getAllByText(sampleFact.title)).toHaveLength(1);
    expect(screen.getAllByText(projectFact.title)).toHaveLength(1);
    expect(load).toHaveBeenNthCalledWith(2, {
      factType: null,
      status: "active",
      cursor: "cursor-1",
    });
    expect(screen.queryByRole("button", { name: "さらに読み込む" })).not.toBeInTheDocument();
  });

  it("reloads the first page when fact type and status filters change", async () => {
    const load = vi.fn().mockResolvedValue({ facts: [], totalActive: 0, nextCursor: null });
    renderPanel({ isLoggedIn: true, api: { load } });
    await waitFor(() => expect(load).toHaveBeenCalledWith({ factType: null, status: "active" }));

    fireEvent.click(screen.getByRole("button", { name: "すべての種類" }));
    fireEvent.click(screen.getByRole("option", { name: "プロジェクト文脈" }));
    await waitFor(() =>
      expect(load).toHaveBeenCalledWith({ factType: "project", status: "active" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "無効化済み" }));
    await waitFor(() =>
      expect(load).toHaveBeenCalledWith({ factType: "project", status: "deprecated" }),
    );
  });

  it("sends the current revision when deprecating and restoring facts", async () => {
    const deprecatedFact = { ...sampleFact, status: "deprecated" as const, revision: 7 };
    const load = vi
      .fn()
      .mockResolvedValueOnce({ facts: [sampleFact], totalActive: 1, nextCursor: null })
      .mockResolvedValueOnce({ facts: [], totalActive: 0, nextCursor: null })
      .mockResolvedValueOnce({ facts: [deprecatedFact], totalActive: 0, nextCursor: null });
    const update = vi.fn().mockResolvedValue(sampleFact);
    const view = renderPanel({ isLoggedIn: true, api: { load, update } });

    await waitFor(() => expect(screen.getByRole("button", { name: "無効化" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "無効化" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(sampleFact.id, {
        revision: sampleFact.revision,
        status: "deprecated",
      }),
    );

    view.unmount();
    const restoreLoad = vi.fn().mockResolvedValue({
      facts: [deprecatedFact],
      totalActive: 0,
      nextCursor: null,
    });
    renderPanel({ isLoggedIn: true, api: { load: restoreLoad, update } });
    await waitFor(() => expect(screen.getByRole("button", { name: "復元" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "復元" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(deprecatedFact.id, {
        revision: deprecatedFact.revision,
        status: "active",
      }),
    );
  });

  it("keeps the editor open and reports API errors", async () => {
    const load = vi.fn().mockResolvedValue({ facts: [], totalActive: 0, nextCursor: null });
    const create = vi.fn().mockRejectedValue(new Error("保存件数の上限に達しました。"));
    renderPanel({ isLoggedIn: true, api: { load, create } });

    fireEvent.click(screen.getByRole("button", { name: /コンテキストを追加/ }));
    fireEvent.change(screen.getByLabelText("タイトル"), { target: { value: "好み" } });
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "簡潔な回答" } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("保存件数の上限に達しました。");
    expect(screen.getByRole("dialog", { name: "コンテキストを追加" })).toBeInTheDocument();
  });

  it("updates the importance when editing a fact", async () => {
    const load = vi.fn().mockResolvedValue({
      facts: [sampleFact],
      totalActive: 1,
      nextCursor: null,
    });
    const update = vi.fn().mockResolvedValue({ ...sampleFact, importance: 25 });
    renderPanel({ isLoggedIn: true, api: { load, update } });

    await waitFor(() => expect(screen.getByText("エディタの好み")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "編集" }));
    fireEvent.click(screen.getByRole("button", { name: "重要度" }));
    fireEvent.click(screen.getByRole("option", { name: "低" }));
    fireEvent.click(screen.getByRole("button", { name: "更新" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(3, {
        revision: 2,
        fact_type: "preference",
        title: "エディタの好み",
        content: "vim キーバインドを使う",
        importance: 25,
      }),
    );
  });

  it("preserves a non-preset importance when editing other fields", async () => {
    const exactImportanceFact = { ...sampleFact, importance: 100 };
    const load = vi.fn().mockResolvedValue({
      facts: [exactImportanceFact],
      totalActive: 1,
      nextCursor: null,
    });
    const update = vi.fn().mockResolvedValue({ ...exactImportanceFact, title: "更新済み" });
    renderPanel({ isLoggedIn: true, api: { load, update } });

    await waitFor(() => expect(screen.getByText("エディタの好み")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "編集" }));
    fireEvent.change(screen.getByLabelText("タイトル"), { target: { value: "更新済み" } });
    fireEvent.click(screen.getByRole("button", { name: "更新" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(3, {
        revision: 2,
        fact_type: "preference",
        title: "更新済み",
        content: "vim キーバインドを使う",
      }),
    );
  });
});
