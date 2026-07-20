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
