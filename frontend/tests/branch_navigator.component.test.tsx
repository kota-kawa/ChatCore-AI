import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BranchNavigator } from "../components/chat_page/branch_navigator";
import type { UiChatMessage } from "../lib/chat_page/types";
import { LocaleProvider } from "../contexts/locale_context";

function makeMessage(overrides: Partial<UiChatMessage> = {}): UiChatMessage {
  return {
    id: "message-1",
    sender: "assistant",
    text: "answer",
    versionIndex: 2,
    versionCount: 3,
    siblingIds: [101, 102, 103],
    ...overrides,
  };
}

describe("BranchNavigator", () => {
  it("switches to the adjacent persisted message versions", () => {
    const onSwitchBranch = vi.fn();
    render(<BranchNavigator message={makeMessage()} onSwitchBranch={onSwitchBranch} />);

    expect(screen.getByText("2/3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "前のバージョン" }));
    fireEvent.click(screen.getByRole("button", { name: "次のバージョン" }));

    expect(onSwitchBranch).toHaveBeenNthCalledWith(1, 101);
    expect(onSwitchBranch).toHaveBeenNthCalledWith(2, 103);
  });

  it("disables unavailable directions and all controls while a switch is pending", () => {
    const { rerender } = render(
      <BranchNavigator
        message={makeMessage({ versionIndex: 1 })}
        onSwitchBranch={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "前のバージョン" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "次のバージョン" })).toBeEnabled();

    rerender(
      <BranchNavigator
        message={makeMessage()}
        disabled
        onSwitchBranch={vi.fn()}
      />
    );
    expect(screen.getAllByRole("button")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ disabled: true }),
        expect.objectContaining({ disabled: true }),
      ])
    );
  });

  it("does not render for a message without branches", () => {
    const { container } = render(
      <BranchNavigator
        message={makeMessage({ versionIndex: 1, versionCount: 1, siblingIds: [101] })}
        onSwitchBranch={vi.fn()}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("uses English accessible labels for an English locale", () => {
    render(
      <LocaleProvider initialLocale="en">
        <BranchNavigator message={makeMessage()} onSwitchBranch={vi.fn()} />
      </LocaleProvider>
    );

    expect(screen.getByRole("button", { name: "Previous branch" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next branch" })).toBeEnabled();
    expect(screen.getByLabelText("Branch 2 of 3")).toBeInTheDocument();
  });
});
