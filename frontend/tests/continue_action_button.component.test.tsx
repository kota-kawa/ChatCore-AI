import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContinueActionButton } from "../components/chat_page/continue_action_button";
import { jaMessages } from "../lib/i18n/catalogs/ja";
import { enMessages } from "../lib/i18n/catalogs/en";

describe("ContinueActionButton", () => {
  it("asks for the rest of a partial answer when pressed", () => {
    const onContinue = vi.fn();
    render(<ContinueActionButton onContinue={onContinue} />);

    fireEvent.click(screen.getByRole("button", { name: "回答の続きを生成" }));

    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it("is inert while another answer is generating", () => {
    const onContinue = vi.fn();
    render(<ContinueActionButton onContinue={onContinue} disabled />);

    const button = screen.getByRole("button", { name: "回答の続きを生成" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  // 日本語: 続きを依頼する文面は、書き直しではなく「続きだけ」を求める必要があります。
  // 全体を書き直させると、保存済みの本文と二重になります。
  // English: The continuation prompt must ask only for the remainder. Asking for a rewrite
  // would duplicate the body that is already saved in history.
  it("prompts for the remainder only, in both languages", () => {
    for (const catalog of [jaMessages, enMessages]) {
      const prompt = catalog["chat.continueAnswerPrompt"];
      expect(prompt).toBeTruthy();
      expect(catalog["chat.continueAnswer"]).toBeTruthy();
    }
    expect(jaMessages["chat.continueAnswerPrompt"]).toContain("続きだけ");
    expect(jaMessages["chat.continueAnswerPrompt"]).toContain("繰り返さず");
    expect(enMessages["chat.continueAnswerPrompt"]).toContain("only the continuation");
    expect(enMessages["chat.continueAnswerPrompt"]).toContain("Do not repeat");
  });
});
