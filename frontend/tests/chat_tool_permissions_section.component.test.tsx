import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatToolPermissionsSection } from "../components/settings/chat_tool_permissions_section";

const { loadToolAutoApprovalsMock, revokeToolAutoApprovalMock, showToastMock } = vi.hoisted(() => ({
  loadToolAutoApprovalsMock: vi.fn(),
  revokeToolAutoApprovalMock: vi.fn(),
  showToastMock: vi.fn(),
}));

vi.mock("../scripts/user/settings/api", () => ({
  loadToolAutoApprovals: loadToolAutoApprovalsMock,
  revokeToolAutoApproval: revokeToolAutoApprovalMock,
}));
vi.mock("../scripts/core/toast", () => ({ showToast: showToastMock }));

const GRANTS = [
  { tool_name: "memo_create", family: "memo", created_at: "2026-09-20T10:00:00Z" },
  { tool_name: "memo_append", family: "memo", created_at: "2026-09-21T10:00:00Z" },
];

beforeEach(() => {
  loadToolAutoApprovalsMock.mockReset();
  revokeToolAutoApprovalMock.mockReset();
  showToastMock.mockReset();
});

describe("ChatToolPermissionsSection", () => {
  it("lists the tools set to always approve when the section opens", async () => {
    loadToolAutoApprovalsMock.mockResolvedValue(GRANTS);
    const { rerender } = render(<ChatToolPermissionsSection isActive={false} />);
    expect(loadToolAutoApprovalsMock).not.toHaveBeenCalled();

    rerender(<ChatToolPermissionsSection isActive />);

    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("メモの作成");
    expect(items[0]).toHaveTextContent("許可した日時");
    expect(items[1]).toHaveTextContent("メモへの追記");
  });

  it("revokes one tool and removes it from the list", async () => {
    loadToolAutoApprovalsMock.mockResolvedValue(GRANTS);
    revokeToolAutoApprovalMock.mockResolvedValue(true);
    render(<ChatToolPermissionsSection isActive />);

    const first = (await screen.findAllByRole("listitem"))[0];
    fireEvent.click(within(first).getByRole("button", { name: "メモの作成: 取り消す" }));

    expect(revokeToolAutoApprovalMock).toHaveBeenCalledWith("memo_create", "取り消せませんでした。");
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect(screen.getByRole("listitem")).toHaveTextContent("メモへの追記");
    expect(showToastMock).toHaveBeenCalledWith("取り消しました。次から実行前に確認します。", { variant: "success" });
  });

  it("keeps the grant listed and reports the error when revoking fails", async () => {
    loadToolAutoApprovalsMock.mockResolvedValue(GRANTS);
    revokeToolAutoApprovalMock.mockRejectedValue(new Error("取り消せませんでした。"));
    render(<ChatToolPermissionsSection isActive />);

    const first = (await screen.findAllByRole("listitem"))[0];
    fireEvent.click(within(first).getByRole("button", { name: "メモの作成: 取り消す" }));

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("取り消せませんでした。", { variant: "error" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(within(first).getByRole("button", { name: "メモの作成: 取り消す" })).toBeEnabled();
  });

  it("shows an empty state when nothing is always approved", async () => {
    loadToolAutoApprovalsMock.mockResolvedValue([]);
    render(<ChatToolPermissionsSection isActive />);

    expect(await screen.findByText("「常に承認」にした操作はありません。")).toBeInTheDocument();
  });

  it("offers a retry when the list cannot be loaded", async () => {
    loadToolAutoApprovalsMock.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(GRANTS);
    render(<ChatToolPermissionsSection isActive />);

    expect(await screen.findByRole("alert")).toHaveTextContent("チャットの権限を読み込めませんでした。");
    fireEvent.click(screen.getByRole("button", { name: "再試行" }));

    expect(await screen.findAllByRole("listitem")).toHaveLength(2);
  });
});
