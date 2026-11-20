// 個人コンテキストの表示と操作を検証する。
// Tests my context panel behavior.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import { MyContextPanel } from "../components/memo/MyContextPanel";
import type { ContextExtractionApi } from "../components/memo/ContextExtractionSetting";
import type { ContextMemoryUseApi } from "../components/memo/ContextMemoryUseSetting";
import type { ContextFact } from "../lib/memo/context_types";

function renderPanel(props: Parameters<typeof MyContextPanel>[0]) {
  const extractionApi: ContextExtractionApi = {
    load: vi.fn().mockResolvedValue({ enabled: false }),
    update: vi.fn().mockImplementation(async ({ enabled }) => ({ enabled })),
    ...props.extractionApi,
  };
  const memoryUseApi: ContextMemoryUseApi = {
    load: vi.fn().mockResolvedValue({ enabled: true }),
    update: vi.fn().mockImplementation(async ({ enabled }) => ({ enabled })),
    ...props.memoryUseApi,
  };
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MyContextPanel {...props} extractionApi={extractionApi} memoryUseApi={memoryUseApi} />
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
  confidence: null,
  last_confirmed_at: null,
  deprecated_reason: null,
  source_count: 0,
  last_mentioned_at: null,
  sources: [],
  superseded_by: null,
  replaces: null,
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

  it("opens the accessible export and import modal from the header", async () => {
    const load = vi.fn().mockResolvedValue({
      facts: [sampleFact],
      totalActive: 1,
      nextCursor: null,
    });
    renderPanel({ isLoggedIn: true, api: { load } });

    await screen.findByText("エディタの好み");
    fireEvent.click(screen.getByRole("button", { name: "持ち運び" }));

    expect(
      screen.getByRole("dialog", { name: "記憶の持ち運び" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /書き出し/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /取り込み/ })).toBeInTheDocument();
  });

  it("puts the auto-save switch on the memory screen and has no pending-approval panel", async () => {
    const load = vi.fn().mockResolvedValue({ facts: [sampleFact], totalActive: 1, nextCursor: null });
    renderPanel({ isLoggedIn: true, api: { load }, extractionApi: { load: vi.fn().mockResolvedValue({ enabled: true }) } });

    await screen.findByText("エディタの好み");
    const toggle = await screen.findByRole("switch", { name: "チャットからの自動保存" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(
      screen.getByText(/上限（200件）に達すると、自動保存されたまま一度も手を入れていない記憶のうち、長く話題に出ていないものから自動で入れ替わります/),
    ).toBeInTheDocument();
    expect(screen.queryByText("承認待ちの提案")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "承認" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "却下" })).not.toBeInTheDocument();
  });

  it("shows saving and using as two separate switches that change independently", async () => {
    const load = vi.fn().mockResolvedValue({ facts: [sampleFact], totalActive: 1, nextCursor: null });
    const extractionUpdate = vi.fn().mockImplementation(async ({ enabled }) => ({ enabled }));
    const memoryUseUpdate = vi.fn().mockImplementation(async ({ enabled }) => ({ enabled }));
    renderPanel({
      isLoggedIn: true,
      api: { load },
      extractionApi: { load: vi.fn().mockResolvedValue({ enabled: true }), update: extractionUpdate },
      memoryUseApi: { load: vi.fn().mockResolvedValue({ enabled: true }), update: memoryUseUpdate },
    });

    const saving = await screen.findByRole("switch", { name: "チャットからの自動保存" });
    const using = await screen.findByRole("switch", { name: "記憶を回答に使う" });
    await waitFor(() => expect(saving).toHaveAttribute("aria-checked", "true"));
    await waitFor(() => expect(using).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText("チャットから自動で記憶する")).toBeInTheDocument();
    expect(screen.getByText("記憶を回答に使う", { selector: "strong" })).toBeInTheDocument();

    fireEvent.click(using);

    await waitFor(() => expect(memoryUseUpdate).toHaveBeenCalledWith({ enabled: false }));
    await waitFor(() => expect(using).toHaveAttribute("aria-checked", "false"));
    expect(saving).toHaveAttribute("aria-checked", "true");
    expect(extractionUpdate).not.toHaveBeenCalled();
  });

  it("marks only the facts the memory limit deactivated in the deactivated list", async () => {
    const load = vi.fn().mockResolvedValue({
      facts: [
        { ...sampleFact, id: 7, title: "上限で外れた記憶", status: "deprecated", deprecated_reason: "capacity" },
        { ...sampleFact, id: 8, title: "自分で無効化した記憶", status: "deprecated", deprecated_reason: "user" },
        { ...sampleFact, id: 9, title: "以前に無効化した記憶", status: "deprecated", deprecated_reason: null },
      ],
      totalActive: 1,
      nextCursor: null,
    });
    renderPanel({ isLoggedIn: true, api: { load } });

    await screen.findByText("上限で外れた記憶");
    fireEvent.click(screen.getByRole("button", { name: "無効化済み" }));

    await waitFor(() => expect(load).toHaveBeenCalledWith({ factType: null, status: "deprecated" }));
    expect(screen.getAllByText("上限のため自動で無効化")).toHaveLength(1);
    const card = screen.getByText("上限で外れた記憶").closest("article");
    expect(card).toHaveTextContent("上限のため自動で無効化");
    expect(screen.getByText("自分で無効化した記憶").closest("article")).not.toHaveTextContent("上限のため自動で無効化");
    expect(screen.getByText("以前に無効化した記憶").closest("article")).not.toHaveTextContent("上限のため自動で無効化");
    // 復元は既存の操作のまま。
    // Restoring stays the existing action.
    expect(within(card as HTMLElement).getByRole("button", { name: "復元" })).toBeInTheDocument();
  });

  it("creates a fact through the editor and reloads", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ facts: [], totalActive: 0, nextCursor: null })
      .mockResolvedValue({ facts: [sampleFact], totalActive: 1, nextCursor: null });
    const create = vi.fn().mockResolvedValue(sampleFact);
    renderPanel({ isLoggedIn: true, api: { load, create } });

    fireEvent.click(screen.getByRole("button", { name: /記憶を追加/ }));
    expect(screen.getByRole("dialog", { name: "記憶を追加" })).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: /記憶を追加/ }));
    expect(screen.getByRole("dialog", { name: "記憶を追加" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });

    // 閉じた直後は外殻を置いたまま、入力していた面を残して薄れさせる
    // Right after closing, the shell stays and keeps the form on screen while it fades
    const overlay = document.getElementById("context-editor-modal");
    expect(overlay).toHaveClass("is-closing");
    expect(overlay).toHaveTextContent("記憶を追加");

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "記憶を追加" })).not.toBeInTheDocument();
      expect(document.body.style.overflow).toBe("");
      expect(overlay).not.toHaveClass("is-closing");
      expect(overlay).not.toHaveTextContent("記憶を追加");
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

    fireEvent.click(screen.getByRole("button", { name: /記憶を追加/ }));
    fireEvent.change(screen.getByLabelText("タイトル"), { target: { value: "好み" } });
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "簡潔な回答" } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("保存件数の上限に達しました。");
    expect(screen.getByRole("dialog", { name: "記憶を追加" })).toBeInTheDocument();
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
