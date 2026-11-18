// 選択ボタンの送信形式と重複回答防止を検証する。
// Tests interactive buttons behavior.

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
  it("composes the localized yes/no label with its question once and then locks the question", () => {
    const onCompose = vi.fn();
    render(<InteractiveButtons buttons={YES_NO} onCompose={onCompose} />);

    expect(screen.getByRole("group", { name: YES_NO.question })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "はい" }));
    fireEvent.click(screen.getByRole("button", { name: "いいえ" }));

    expect(onCompose).toHaveBeenCalledTimes(1);
    expect(onCompose).toHaveBeenCalledWith(`${YES_NO.question}\nはい`);
    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "いいえ" })).toBeDisabled();
  });

  it("composes the pressed option of a single choice with its question", () => {
    const onCompose = vi.fn();
    render(<InteractiveButtons buttons={SINGLE} onCompose={onCompose} />);

    fireEvent.click(screen.getByRole("button", { name: "表" }));

    expect(onCompose).toHaveBeenCalledWith(`${SINGLE.question}\n表`);
  });

  it("composes every ticked option once with its question in the presented order", () => {
    const onCompose = vi.fn();
    render(<InteractiveButtons buttons={MULTIPLE} onCompose={onCompose} />);
    const submit = screen.getByRole("button", { name: "入力欄へ反映" });

    expect(screen.getByText("当てはまるものをすべて選んでください")).toBeInTheDocument();
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(onCompose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox", { name: "リスク" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "概要" }));
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(onCompose).toHaveBeenCalledTimes(1);
    expect(onCompose).toHaveBeenCalledWith(`${MULTIPLE.question}\n概要、リスク`);
    fireEvent.click(submit);
    expect(onCompose).toHaveBeenCalledTimes(1);
    expect(submit).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "費用" })).toBeDisabled();
  });

  it("cannot compose once every option is unticked again", () => {
    const onCompose = vi.fn();
    render(<InteractiveButtons buttons={MULTIPLE} onCompose={onCompose} />);
    const risk = screen.getByRole("checkbox", { name: "リスク" });

    fireEvent.click(risk);
    fireEvent.click(risk);

    expect(screen.getByRole("button", { name: "入力欄へ反映" })).toBeDisabled();
  });

  it("uses the English labels and separator in the English UI", () => {
    const onSubmit = vi.fn();
    render(
      <LocaleProvider initialLocale="en">
        <InteractiveButtons buttons={MULTIPLE} onCompose={onSubmit} />
        <InteractiveButtons buttons={YES_NO} onCompose={onSubmit} />
      </LocaleProvider>,
    );

    expect(screen.getByRole("button", { name: "Yes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "概要" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "費用" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to message" }));

    expect(onSubmit).toHaveBeenCalledWith(`${MULTIPLE.question}\n概要, 費用`);
  });

  it("stays inert once the question has been answered", () => {
    const onSubmit = vi.fn();
    render(
      <>
        <InteractiveButtons buttons={SINGLE} onCompose={onSubmit} disabled />
        <InteractiveButtons buttons={MULTIPLE} onCompose={onSubmit} disabled />
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
    expect(screen.getByRole("button", { name: "入力欄へ反映" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.queryByText("対話型ボタンは共有画面では動作しません。")).not.toBeInTheDocument();
  });
});

describe("choice buttons inside message parts", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "移行すると3列が削除されます。" },
    { type: "interactive_buttons", buttons: YES_NO },
  ];

  it("hands the question and chosen option to the composer", () => {
    const onCompose = vi.fn();
    render(<BotMessageParts fallbackText="" parts={parts} onCompose={onCompose} />);

    fireEvent.click(screen.getByRole("button", { name: "はい" }));

    expect(onCompose).toHaveBeenCalledWith(`${YES_NO.question}\nはい`);
  });

  it("disables the buttons of an answered message", () => {
    const onCompose = vi.fn();
    render(<BotMessageParts fallbackText="" parts={parts} onCompose={onCompose} composeDisabled />);

    fireEvent.click(screen.getByRole("button", { name: "はい" }));

    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    expect(onCompose).not.toHaveBeenCalled();
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
    expect(screen.getByRole("button", { name: "入力欄へ反映" })).toBeDisabled();
    expect(screen.getAllByText("対話型ボタンは共有画面では動作しません。")).toHaveLength(2);
  });
});
