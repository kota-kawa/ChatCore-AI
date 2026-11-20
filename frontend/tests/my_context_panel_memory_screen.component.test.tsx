// 記憶の画面の出典・置き換えの履歴と元に戻す・検索・完全な削除・すべての削除を検証する。
// Tests the memory screen's sources, replacement history and undo, search, permanent delete and delete-all.

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import { MyContextPanel } from "../components/memo/MyContextPanel";
import { LocaleProvider } from "../contexts/locale_context";
import type { ContextFact } from "../lib/memo/context_types";

// 設定のスイッチは別のテストが見る。ここでは取得の呼び出し回数に影響しない固定の応答を返す（harness の外で作り、再レンダーで参照が変わらないようにする）。
// The setting switches are covered elsewhere; fixed responses are created outside the render so their references stay stable across re-renders.
const extractionApi = {
  load: vi.fn().mockResolvedValue({ enabled: true }),
  update: vi.fn().mockImplementation(async ({ enabled }: { enabled: boolean }) => ({ enabled })),
};
const memoryUseApi = {
  load: vi.fn().mockResolvedValue({ enabled: true }),
  update: vi.fn().mockImplementation(async ({ enabled }: { enabled: boolean }) => ({ enabled })),
};

function renderPanel(api: Parameters<typeof MyContextPanel>[0]["api"], locale: "ja" | "en" = "ja") {
  return render(
    <LocaleProvider initialLocale={locale}>
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <MyContextPanel isLoggedIn api={api} extractionApi={extractionApi} memoryUseApi={memoryUseApi} />
      </SWRConfig>
    </LocaleProvider>,
  );
}

function fact(overrides: Partial<ContextFact> = {}): ContextFact {
  return {
    id: 1,
    fact_type: "profile",
    title: "住所",
    content: "東京に住んでいる",
    status: "active",
    revision: 1,
    source_kind: "chat",
    importance: 50,
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
    ...overrides,
  };
}

const page = (facts: ContextFact[], totalActive = facts.length, nextCursor: string | null = null) => ({
  facts,
  totalActive,
  nextCursor,
});

describe("MyContextPanel sources", () => {
  const withSources = fact({
    id: 5,
    title: "住所",
    source_count: 4,
    last_mentioned_at: "2026-11-18T03:00:00+00:00",
    sources: [
      { chat_room_id: "room-new", evidence: "いま東京に住んでいます", observed_at: "2026-11-18T03:00:00+00:00" },
      { chat_room_id: "room/old&x=1", evidence: "<img src=x onerror=alert(1)> 大阪から引っ越した", observed_at: "2026-10-01T03:00:00+00:00" },
    ],
  });

  it("shows when it was last mentioned and the source count, with the sources closed at first", async () => {
    renderPanel({ load: vi.fn().mockResolvedValue(page([withSources])) });

    const card = (await screen.findByText("住所")).closest("article") as HTMLElement;
    expect(card).toHaveTextContent("最後に話題に出た日: 2026");
    const toggle = within(card).getByRole("button", { name: "出典（4件）" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(card).queryByText(/いま東京に住んでいます/)).not.toBeInTheDocument();
  });

  it("opens the sources to show quotes as plain text and links to each conversation", async () => {
    renderPanel({ load: vi.fn().mockResolvedValue(page([withSources])) });

    const card = (await screen.findByText("住所")).closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "出典（4件）" }));

    expect(within(card).getByRole("button", { name: "出典（4件）" })).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByText("いま東京に住んでいます")).toBeInTheDocument();
    // 引用は HTML として解釈されず、そのままの文字として出る。
    // A quote is not interpreted as HTML; it appears as literal text.
    expect(card.querySelector("img")).toBeNull();
    expect(within(card).getByText(/<img src=x onerror=alert\(1\)> 大阪から引っ越した/)).toBeInTheDocument();

    const links = within(card).getAllByRole("link", { name: "この会話を開く" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/?room=room-new", "/?room=room%2Fold%26x%3D1"]);
    expect(within(card).getByText("新しい順に2件を表示しています（全4件）")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "出典（4件）" }));
    expect(within(card).queryByText("いま東京に住んでいます")).not.toBeInTheDocument();
  });

  it("shows only the origin label for a memory without sources, and a translated MCP label", async () => {
    renderPanel({
      load: vi.fn().mockResolvedValue(
        page([
          fact({ id: 1, title: "手入力", source_kind: "manual" }),
          fact({ id: 2, title: "外部から", source_kind: "mcp" }),
          fact({ id: 3, title: "取り込み済みの記憶", source_kind: "import" }),
        ]),
      ),
    });

    await screen.findByText("手入力");
    expect(screen.getByText("手入力").closest("article")).toHaveTextContent("出典: 手動");
    expect(screen.getByText("外部から").closest("article")).toHaveTextContent("出典: MCP");
    expect(screen.getByText("取り込み済みの記憶").closest("article")).toHaveTextContent("出典: インポート");
    expect(screen.queryByRole("button", { name: /^出典（/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/最後に話題に出た日/)).not.toBeInTheDocument();
  });

  it("renders in English", async () => {
    renderPanel({ load: vi.fn().mockResolvedValue(page([withSources])) }, "en");

    const card = (await screen.findByText("住所")).closest("article") as HTMLElement;
    expect(card).toHaveTextContent("Last mentioned:");
    fireEvent.click(within(card).getByRole("button", { name: "Sources (4)" }));
    expect(within(card).getAllByRole("link", { name: "Open this conversation" })).toHaveLength(2);
    expect(within(card).getByText("Showing the newest 2 of 4")).toBeInTheDocument();
  });
});

describe("MyContextPanel replacement history", () => {
  it("names the newer memory on a replaced memory in the deactivated list, and keeps restore as is", async () => {
    const load = vi.fn().mockResolvedValue(
      page(
        [
          fact({ id: 7, title: "旧住所", status: "deprecated", deprecated_reason: "superseded", superseded_by: { id: 8, title: "新住所" } }),
          fact({ id: 9, title: "消された置き換え先", status: "deprecated", deprecated_reason: "superseded", superseded_by: null }),
          fact({ id: 10, title: "上限で外れた", status: "deprecated", deprecated_reason: "capacity" }),
          fact({ id: 11, title: "自分で無効化", status: "deprecated", deprecated_reason: "user" }),
        ],
        1,
      ),
    );
    renderPanel({ load });

    fireEvent.click(await screen.findByRole("button", { name: "無効化済み" }));
    await screen.findByText("旧住所");

    const replaced = screen.getByText("旧住所").closest("article") as HTMLElement;
    expect(replaced).toHaveTextContent("新しい記憶に置き換え済み：新住所");
    expect(within(replaced).getByRole("button", { name: "復元" })).toBeInTheDocument();
    expect(screen.getByText("消された置き換え先").closest("article")).toHaveTextContent("新しい記憶に置き換え済み（置き換えた記憶は削除されました）");
    expect(screen.getByText("上限で外れた").closest("article")).toHaveTextContent("上限のため自動で無効化");
    expect(screen.getByText("上限で外れた").closest("article")).not.toHaveTextContent("置き換え済み");
    expect(screen.getByText("自分で無効化").closest("article")).not.toHaveTextContent("置き換え済み");
  });

  it("shows the previous memory with Undo on an active memory that replaced one, and undoes with the new memory's revision", async () => {
    const replacing = fact({
      id: 8,
      title: "新住所",
      content: "大阪に住んでいる",
      revision: 3,
      replaces: { id: 7, title: "旧住所", content: "東京に住んでいる" },
    });
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([replacing]))
      .mockResolvedValue(page([fact({ id: 7, title: "旧住所", content: "東京に住んでいる", revision: 5 })]));
    const revert = vi.fn().mockResolvedValue({ fact: {}, restored_fact: {} });
    renderPanel({ load, revert });

    const card = (await screen.findByText("新住所")).closest("article") as HTMLElement;
    expect(card).toHaveTextContent("以前の記憶：東京に住んでいる");
    fireEvent.click(within(card).getByRole("button", { name: "元に戻す" }));

    await waitFor(() => expect(revert).toHaveBeenCalledWith(8, 3));
    expect(await screen.findByRole("status")).toHaveTextContent("元に戻しました。");
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("旧住所")).toBeInTheDocument();
    expect(screen.queryByText("新住所")).not.toBeInTheDocument();
  });

  it("does not show Undo on a memory that replaced nothing, and reports a failed undo", async () => {
    const replacing = fact({ id: 8, title: "新住所", replaces: { id: 7, title: "旧", content: "古い" } });
    const revert = vi.fn().mockRejectedValue(new Error("この置き換えは元に戻せません。"));
    renderPanel({ load: vi.fn().mockResolvedValue(page([fact({ id: 1, title: "ふつうの記憶" }), replacing])), revert });

    await screen.findByText("ふつうの記憶");
    expect(screen.getAllByRole("button", { name: "元に戻す" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "元に戻す" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("この置き換えは元に戻せません。");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("MyContextPanel search", () => {
  it("fetches once after typing pauses, with the trimmed query", async () => {
    const load = vi.fn().mockResolvedValue(page([fact()]));
    renderPanel({ load });
    await screen.findByText("住所");
    expect(load).toHaveBeenCalledTimes(1);

    const input = screen.getByRole("searchbox", { name: "記憶を検索" });
    fireEvent.change(input, { target: { value: "東" } });
    fireEvent.change(input, { target: { value: "東京" } });
    fireEvent.change(input, { target: { value: "  東京 " } });

    // 入力のたびには取得しない。
    // It does not fetch on every keystroke.
    expect(load).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(load).toHaveBeenLastCalledWith({ factType: null, status: "active", query: "東京" });
    expect(load.mock.calls.map(([params]) => params.query)).toEqual([undefined, "東京"]);
  });

  it("combines the query with the type and status filters and with paging", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([fact()]))
      .mockResolvedValueOnce(page([fact()], 1, "cursor-1"))
      .mockResolvedValueOnce(page([fact({ id: 2, title: "二ページ目" })]));
    renderPanel({ load });
    await screen.findByText("住所");

    fireEvent.change(screen.getByRole("searchbox", { name: "記憶を検索" }), { target: { value: "東京" } });
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({ factType: null, status: "active", query: "東京" }));

    fireEvent.click(await screen.findByRole("button", { name: "さらに読み込む" }));
    await waitFor(() =>
      expect(load).toHaveBeenLastCalledWith({ factType: null, status: "active", cursor: "cursor-1", query: "東京" }),
    );
    await screen.findByText("二ページ目");

    fireEvent.click(screen.getByRole("button", { name: "無効化済み" }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({ factType: null, status: "deprecated", query: "東京" }));
  });

  it("shows an empty-result message for a query with no match, and the clear button restores the list", async () => {
    const load = vi.fn().mockImplementation(async (params: { query?: string }) => page(params.query ? [] : [fact()]));
    renderPanel({ load });
    await screen.findByText("住所");

    fireEvent.change(screen.getByRole("searchbox", { name: "記憶を検索" }), { target: { value: "存在しない語" } });
    expect(await screen.findByText("「存在しない語」に一致する記憶はありません。")).toBeInTheDocument();
    expect(screen.queryByText("まだ記憶がありません。「記憶を追加」から保存してみましょう。")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "検索をクリア" }));
    expect(screen.getByRole("searchbox", { name: "記憶を検索" })).toHaveValue("");
    expect(await screen.findByText("住所")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "検索をクリア" })).not.toBeInTheDocument();
  });

  it("treats a punctuation-only query as no search: no re-fetch and no search-style empty message", async () => {
    // サーバーは語が 0 個の検索語を「検索なし」として全件を返す。画面も同じ取得・同じ表示にする。
    // The server treats a query with no terms as "no search" and returns everything; the screen fetches and shows the same.
    const load = vi.fn().mockResolvedValue(page([]));
    renderPanel({ load });
    await screen.findByText("まだ記憶がありません。「記憶を追加」から保存してみましょう。");

    fireEvent.change(screen.getByRole("searchbox", { name: "記憶を検索" }), { target: { value: " ,、 " } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 450));
    });
    expect(load).toHaveBeenCalledTimes(1);
    expect(screen.getByText("まだ記憶がありません。「記憶を追加」から保存してみましょう。")).toBeInTheDocument();
    expect(screen.queryByText(/に一致する記憶はありません/)).not.toBeInTheDocument();
  });

  it("does not re-fetch for a query that only changes by whitespace", async () => {
    const load = vi.fn().mockResolvedValue(page([fact()]));
    renderPanel({ load });
    await screen.findByText("住所");

    const input = screen.getByRole("searchbox", { name: "記憶を検索" });
    fireEvent.change(input, { target: { value: "  " } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 450));
    });
    expect(load).toHaveBeenCalledTimes(1);
  });
});

describe("MyContextPanel permanent delete", () => {
  it("confirms in a modal that explains the difference from deactivating, and deletes with the revision", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([fact({ id: 3, title: "消す記憶", revision: 4 })]))
      .mockResolvedValue(page([]));
    const deleteOne = vi.fn().mockResolvedValue(undefined);
    renderPanel({ load, deleteOne });

    const card = (await screen.findByText("消す記憶")).closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "完全に削除" }));

    const dialog = await screen.findByRole("dialog", { name: "この記憶を完全に削除しますか？" });
    expect(dialog).toHaveTextContent("消す記憶");
    expect(dialog).toHaveTextContent("文面と出典を消します。同じ内容をチャットでまた話すと、もう一度覚えることがあります。");
    expect(dialog).toHaveTextContent("「無効化」を使ってください");
    expect(deleteOne).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "完全に削除" }));
    await waitFor(() => expect(deleteOne).toHaveBeenCalledWith(3, 4));
    expect(await screen.findByRole("status")).toHaveTextContent("記憶を完全に削除しました。");
    await waitFor(() => expect(screen.queryByText("消す記憶")).not.toBeInTheDocument());
  });

  it("deletes nothing when cancelled and keeps the modal open with an error when the delete fails", async () => {
    const load = vi.fn().mockResolvedValue(page([fact({ id: 3, title: "消す記憶", revision: 4 })]));
    const deleteOne = vi.fn().mockRejectedValue(new Error("他の場所で先に更新されました。"));
    renderPanel({ load, deleteOne });

    const card = (await screen.findByText("消す記憶")).closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "完全に削除" }));
    let dialog = await screen.findByRole("dialog", { name: "この記憶を完全に削除しますか？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    expect(deleteOne).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "この記憶を完全に削除しますか？" })).not.toBeInTheDocument());

    fireEvent.click(within(card).getByRole("button", { name: "完全に削除" }));
    dialog = await screen.findByRole("dialog", { name: "この記憶を完全に削除しますか？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "完全に削除" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("他の場所で先に更新されました。");
    expect(card).toBeInTheDocument();
  });

  it("offers permanent delete on a deactivated memory too", async () => {
    const load = vi.fn().mockResolvedValue(page([fact({ id: 3, title: "無効な記憶", status: "deprecated" })], 0));
    renderPanel({ load });

    fireEvent.click(await screen.findByRole("button", { name: "無効化済み" }));
    const card = (await screen.findByText("無効な記憶")).closest("article") as HTMLElement;
    expect(within(card).getByRole("button", { name: "完全に削除" })).toBeInTheDocument();
  });
});

describe("MyContextPanel delete all", () => {
  it("needs the confirmation box before deleting, shows the count and that it cannot be undone, then reloads", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([fact()], 7))
      .mockResolvedValue(page([], 0));
    const deleteAll = vi.fn().mockResolvedValue(9);
    renderPanel({ load, deleteAll });
    await screen.findByText("住所");

    fireEvent.click(screen.getByRole("button", { name: "すべての記憶を削除…" }));
    const dialog = await screen.findByRole("dialog", { name: "すべての記憶を削除しますか？" });
    expect(dialog).toHaveTextContent("有効な記憶7件と、無効化済みの記憶、それぞれの出典をすべて消します。この操作は取り消せません。");
    expect(dialog).toHaveTextContent("「チャットから自動で記憶する」と「記憶を回答に使う」の設定は変わりません");

    const confirm = within(dialog).getByRole("button", { name: "すべて削除" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(deleteAll).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "取り消せないことを理解しました" }));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(deleteAll).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("status")).toHaveTextContent("9件の記憶を削除しました。");
    await waitFor(() => expect(screen.queryByText("住所")).not.toBeInTheDocument());
    // 設定には触れない。
    // The settings are not touched.
    expect(extractionApi.update).not.toHaveBeenCalled();
    expect(memoryUseApi.update).not.toHaveBeenCalled();
  });

  it("clears the confirmation box on every open and keeps the modal open with an error when the delete fails", async () => {
    const deleteAll = vi.fn().mockRejectedValue(new Error("削除できませんでした。"));
    renderPanel({ load: vi.fn().mockResolvedValue(page([fact()], 1)), deleteAll });
    await screen.findByText("住所");

    fireEvent.click(screen.getByRole("button", { name: "すべての記憶を削除…" }));
    let dialog = await screen.findByRole("dialog", { name: "すべての記憶を削除しますか？" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "取り消せないことを理解しました" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "すべて削除" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("削除できませんでした。");

    fireEvent.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "すべての記憶を削除しますか？" })).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "すべての記憶を削除…" }));
    dialog = await screen.findByRole("dialog", { name: "すべての記憶を削除しますか？" });
    expect(within(dialog).getByRole("checkbox", { name: "取り消せないことを理解しました" })).not.toBeChecked();
    expect(within(dialog).getByRole("button", { name: "すべて削除" })).toBeDisabled();
  });
});
