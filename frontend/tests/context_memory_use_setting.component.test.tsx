// 記憶の「記憶を回答に使う」スイッチの表示・切り替え・失敗時の挙動を検証する。
// Tests the switch for using memory in answers: display, toggling, and failures.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import {
  ContextMemoryUseSetting,
  type ContextMemoryUseApi,
} from "../components/memo/ContextMemoryUseSetting";

function renderSetting(api?: Partial<ContextMemoryUseApi>) {
  const completeApi: ContextMemoryUseApi = {
    load: vi.fn().mockResolvedValue({ enabled: true }),
    update: vi.fn().mockImplementation(async ({ enabled }) => ({ enabled })),
    ...api,
  };
  return {
    ...render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <ContextMemoryUseSetting api={completeApi} />
      </SWRConfig>,
    ),
    api: completeApi,
  };
}

describe("ContextMemoryUseSetting", () => {
  it("explains that saved memory is used in answers, stays saved when off, and is never used in temporary chats", async () => {
    renderSetting();

    const toggle = await screen.findByRole("switch", { name: "記憶を回答に使う" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText("記憶を回答に使う", { selector: "strong" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "有効にすると、保存した記憶をチャットの回答に毎回使います。無効にすると、記憶は保存されたまま回答には使われません。一時チャットでは常に使いません。記憶を保存するかどうかは「チャットから自動で記憶する」で別に設定します。",
      ),
    ).toBeInTheDocument();
  });

  it("is a switch the owner can turn off, sending only the new value", async () => {
    let resolveUpdate: ((value: { enabled: boolean }) => void) | undefined;
    const update = vi.fn().mockImplementation(
      () =>
        new Promise<{ enabled: boolean }>((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    renderSetting({ update });

    const toggle = await screen.findByRole("switch", { name: "記憶を回答に使う" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));

    fireEvent.click(toggle);

    await waitFor(() => expect(update).toHaveBeenCalledWith({ enabled: false }));
    expect(toggle).toBeDisabled();
    resolveUpdate?.({ enabled: false });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(toggle).not.toBeDisabled();
  });

  it("reports update errors and keeps the setting as it was", async () => {
    const update = vi.fn().mockRejectedValue(new Error("設定を更新できませんでした。"));
    renderSetting({ update });

    const toggle = await screen.findByRole("switch", { name: "記憶を回答に使う" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    fireEvent.click(toggle);

    expect(await screen.findByRole("alert")).toHaveTextContent("設定を更新できませんでした。");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).not.toBeDisabled();
  });

  it("disables the switch and reports the error when the setting cannot be loaded", async () => {
    renderSetting({ load: vi.fn().mockRejectedValue(new Error("設定を取得できませんでした。")) });

    expect(await screen.findByRole("alert")).toHaveTextContent("設定を取得できませんでした。");
    expect(screen.getByRole("switch", { name: "記憶を回答に使う" })).toBeDisabled();
  });
});
