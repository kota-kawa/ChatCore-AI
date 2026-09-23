import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecentChatsStrip } from "../components/chat_page/recent_chats_strip";
import { HomePageContextProvider } from "../contexts/chat_page/home_page_context";
import type { ChatRoom } from "../lib/chat_page/types";

type Controller = Parameters<typeof HomePageContextProvider>[0]["controller"];

// ピン留め直後は再取得まで配列の途中に残るので、あえて 3 番目に置く
// Right after pinning, the room stays mid-array until the refetch, so place it third on purpose
const rooms: ChatRoom[] = [
  { id: "a", title: "沖縄旅行のプラン", mode: "normal", lastActivityAt: "2026-09-23T10:00:00" },
  { id: "b", title: "", mode: "temporary", lastActivityAt: "2026-09-22T10:00:00" },
  { id: "p", title: "ピン留め済み", mode: "normal", pinnedAt: "2026-09-22T10:00:00", lastActivityAt: "2026-09-01T10:00:00" },
  { id: "c", title: "C", mode: "normal", lastActivityAt: "2026-09-21T10:00:00" },
  { id: "d", title: "D", mode: "normal", lastActivityAt: "2026-09-20T10:00:00" },
  { id: "e", title: "E", mode: "normal", lastActivityAt: "2026-09-19T10:00:00" },
  { id: "f", title: "F（6件目）", mode: "normal", lastActivityAt: "2026-09-18T10:00:00" },
];

function renderStrip(overrides: { loggedIn?: boolean; chatRooms?: ChatRoom[] } = {}) {
  const switchChatRoom = vi.fn();
  const handleAccessChat = vi.fn(async () => undefined);
  // Provider は controller の各フィールドを読むだけなので、この部品が使う値だけを渡す。
  // The provider only reads controller fields, so pass just what this component consumes.
  const controller = {
    loggedIn: overrides.loggedIn ?? true,
    chatRooms: overrides.chatRooms ?? rooms,
    switchChatRoom,
    handleAccessChat,
  } as unknown as Controller;
  render(
    <HomePageContextProvider controller={controller}>
      <RecentChatsStrip />
    </HomePageContextProvider>,
  );
  return { switchChatRoom, handleAccessChat };
}

describe("RecentChatsStrip", () => {
  it("未ログイン時とルーム 0 件のときは描画しない", () => {
    renderStrip({ loggedIn: false });
    expect(screen.queryByRole("navigation", { name: "最近のチャット" })).toBeNull();

    renderStrip({ chatRooms: [] });
    expect(screen.queryByRole("navigation", { name: "最近のチャット" })).toBeNull();
  });

  it("ピン留めを先頭にしたサイドバーと同じ並びで先頭 5 件だけをチップにし、空タイトルは新規チャットで補う", () => {
    renderStrip();

    const chips = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(chips).toEqual(["ピン留め済み", "沖縄旅行のプラン", "新規チャット", "C", "D"]);
    expect(screen.queryByText("F（6件目）")).toBeNull();
    // ピン留めは並び順だけでは分からないので、チップにピンの印を付ける
    // Pinned rooms are not distinguishable by order alone, so the chip carries a pin mark
    expect(screen.getByRole("button", { name: "ピン留め済み" }).querySelector(".recent-chats__pin")).not.toBeNull();
    expect(screen.getByRole("button", { name: "沖縄旅行のプラン" }).querySelector(".recent-chats__pin")).toBeNull();
  });

  it("チップはそのルームを開き、「すべて見る」は一覧への入口を呼ぶ", () => {
    const { switchChatRoom, handleAccessChat } = renderStrip();

    fireEvent.click(screen.getByRole("button", { name: "新規チャット" }));
    expect(switchChatRoom).toHaveBeenCalledWith("b", "temporary");
    expect(handleAccessChat).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "すべて見る" }));
    expect(handleAccessChat).toHaveBeenCalledTimes(1);
    expect(switchChatRoom).toHaveBeenCalledTimes(1);
  });
});
