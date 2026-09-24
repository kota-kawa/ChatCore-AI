import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BotMessageParts } from "../components/chat_page/bot_message_parts";
import { InteractiveButtons } from "../components/chat_page/interactive_buttons";
import { SharedChatMessageParts } from "../components/shared_chat/shared_chat_message_parts";
import { LocaleProvider } from "../contexts/locale_context";
import type { ChatMessagePart, InteractiveButtonsV1 } from "../lib/chat_page/types";

const YES_NO: InteractiveButtonsV1 = { type: "yes_no", question: "このまま移行を実行しますか？" };
const SINGLE: InteractiveButtonsV1 = {
  type: "multiple_choice",
  question: "どの形式でまとめますか？",
  options: ["箇条書き", "表", "文章"],
};
const MULTIPLE: InteractiveButtonsV1 = {
  type: "multiple_select",
  question: "レポートに含める章を選んでください",
  options: ["概要", "費用", "リスク"],
};

describe("InteractiveButtons", () => {
  it("sends the localized yes/no label once and then locks the question", () => {
    const onSubmit = vi.fn();
    render(<InteractiveButtons buttons={YES_NO} onSubmit={onSubmit} />);

    expect(screen.getByRole("group", { name: YES_NO.question })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "はい" }));
    fireEvent.click(screen.getByRole("button", { name: "いいえ" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("はい");
    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "いいえ" })).toBeDisabled();
  });

  it("sends the pressed option of a single choice as is", () => {
    const onSubmit = vi.fn();
    render(<InteractiveButtons buttons={SINGLE} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "表" }));

    expect(onSubmit).toHaveBeenCalledWith("表");
  });

  it("sends every ticked option of a multiple select together, in the presented order", () => {
    const onSubmit = vi.fn();
    render(<InteractiveButtons buttons={MULTIPLE} onSubmit={onSubmit} />);
    const submit = screen.getByRole("button", { name: "選択して送信" });

    expect(screen.getByText("当てはまるものをすべて選んでください")).toBeInTheDocument();
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox", { name: "リスク" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "概要" }));
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("概要、リスク");
    expect(submit).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "費用" })).toBeDisabled();
  });

  it("cannot send once every option is unticked again", () => {
    const onSubmit = vi.fn();
    render(<InteractiveButtons buttons={MULTIPLE} onSubmit={onSubmit} />);
    const risk = screen.getByRole("checkbox", { name: "リスク" });

    fireEvent.click(risk);
    fireEvent.click(risk);

    expect(screen.getByRole("button", { name: "選択して送信" })).toBeDisabled();
  });

  it("uses the English labels and separator in the English UI", () => {
    const onSubmit = vi.fn();
    render(
      <LocaleProvider initialLocale="en">
        <InteractiveButtons buttons={MULTIPLE} onSubmit={onSubmit} />
        <InteractiveButtons buttons={YES_NO} onSubmit={onSubmit} />
      </LocaleProvider>,
    );

    expect(screen.getByRole("button", { name: "Yes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "概要" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "費用" }));
    fireEvent.click(screen.getByRole("button", { name: "Send selection" }));

    expect(onSubmit).toHaveBeenCalledWith("概要, 費用");
  });

  it("stays inert once the question has been answered", () => {
    const onSubmit = vi.fn();
    render(
      <>
        <InteractiveButtons buttons={SINGLE} onSubmit={onSubmit} disabled />
        <InteractiveButtons buttons={MULTIPLE} onSubmit={onSubmit} disabled />
      </>,
    );

    for (const option of SINGLE.options ?? []) {
      const button = screen.getByRole("button", { name: option });
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    for (const option of MULTIPLE.options ?? []) {
      expect(screen.getByRole("checkbox", { name: option })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "選択して送信" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.queryByText("対話型ボタンは共有画面では動作しません。")).not.toBeInTheDocument();
  });
});

describe("choice buttons inside message parts", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "移行すると3列が削除されます。" },
    { type: "interactive_buttons", buttons: YES_NO },
  ];

  it("hands the chosen option to the chat send path", () => {
    const onChoiceSubmit = vi.fn();
    render(<BotMessageParts fallbackText="" parts={parts} onChoiceSubmit={onChoiceSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "はい" }));

    expect(onChoiceSubmit).toHaveBeenCalledWith("はい");
  });

  it("disables the buttons of an answered message", () => {
    const onChoiceSubmit = vi.fn();
    render(<BotMessageParts fallbackText="" parts={parts} onChoiceSubmit={onChoiceSubmit} choicesDisabled />);

    fireEvent.click(screen.getByRole("button", { name: "はい" }));

    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    expect(onChoiceSubmit).not.toHaveBeenCalled();
  });

  it("renders the shared view read-only with a note", () => {
    render(
      <SharedChatMessageParts
        fallbackText=""
        parts={[...parts, { type: "interactive_buttons", buttons: MULTIPLE }]}
      />,
    );

    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "いいえ" })).toBeDisabled();
    for (const option of MULTIPLE.options ?? []) {
      expect(screen.getByRole("checkbox", { name: option })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "選択して送信" })).toBeDisabled();
    expect(screen.getAllByText("対話型ボタンは共有画面では動作しません。")).toHaveLength(2);
  });
});
