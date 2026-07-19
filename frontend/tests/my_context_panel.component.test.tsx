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
    fireEvent.change(screen.getByPlaceholderText(/タイトル/), {
      target: { value: "エディタの好み" },
    });
    fireEvent.change(screen.getByPlaceholderText(/内容/), {
      target: { value: "vim キーバインドを使う" },
    });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        fact_type: "preference",
        title: "エディタの好み",
        content: "vim キーバインドを使う",
      }),
    );
  });
});
