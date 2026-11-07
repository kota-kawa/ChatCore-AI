// ルーム操作メニューを Escape で閉じ、開く「⋮」ボタンへフォーカスが戻ることを検証する。
// Tests that Escape closes the room actions menu and returns focus to its "⋮" button.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatRoomCard } from "../components/chat_page/chat_room_card";
import type { ChatRoom } from "../lib/chat_page/types";

const setOpenRoomActionsFor = vi.fn();
let openRoomActionsFor: string | null = null;

vi.mock("../contexts/chat_page/home_page_context", () => ({
  useHomePageChatContext: () => ({
    currentRoomId: null,
    openRoomActionsFor,
    isRoomSelectionMode: false,
    selectedRoomIds: new Set<string>(),
    switchChatRoom: vi.fn(),
    setOpenRoomActionsFor,
    handleRenameRoom: vi.fn(),
    handleToggleRoomPin: vi.fn(),
    handleDeleteRoom: vi.fn(),
    enterRoomSelectionMode: vi.fn(),
    toggleRoomSelection: vi.fn(),
  }),
  useHomePageProjectContext: () => ({
    projects: [],
    isProjectsLoading: false,
    openNewProjectModal: vi.fn(),
    assignRoomToProject: vi.fn(),
  }),
}));
vi.mock("../contexts/locale_context", () => ({
  useTranslation: () => ({ locale: "ja", t: (key: string) => key }),
}));

const room: ChatRoom = { id: "r1", title: "相談", mode: "normal", lastActivityAt: "2026-09-20T10:00:00" };

describe("ChatRoomCard actions menu and Escape", () => {
  beforeEach(() => {
    setOpenRoomActionsFor.mockClear();
  });

  it("closes the open menu on Escape and focuses the trigger", () => {
    openRoomActionsFor = "r1";
    render(<ChatRoomCard room={room} />);
    const trigger = screen.getByRole("button", { name: "相談 の操作メニューを開く" });
    screen.getAllByRole("menuitem")[0].focus();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    expect(setOpenRoomActionsFor).toHaveBeenCalledWith(null);
    expect(trigger).toHaveFocus();
  });

  it("does nothing on Escape while another room's menu is open", () => {
    openRoomActionsFor = "other";
    render(<ChatRoomCard room={room} />);

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(setOpenRoomActionsFor).not.toHaveBeenCalled();
  });
});
