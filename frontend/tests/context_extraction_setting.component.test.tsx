// 記憶の「チャットから自動で記憶する」スイッチの表示・切り替え・失敗時の挙動を検証する。
// Tests the switch for remembering from chats automatically: display, toggling, and failures.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import {
  ContextExtractionSetting,
  type ContextExtractionApi,
} from "../components/memo/ContextExtractionSetting";

function renderSetting(api?: Partial<ContextExtractionApi>) {
  const completeApi: ContextExtractionApi = {
    load: vi.fn().mockResolvedValue({ enabled: false }),
    update: vi.fn().mockImplementation(async ({ enabled }) => ({ enabled })),
    ...api,
  };
  return {
    ...render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <ContextExtractionSetting api={completeApi} />
      </SWRConfig>,
    ),
    api: completeApi,
  };
}

describe("ContextExtractionSetting", () => {
  it("explains that chat content is saved automatically and the oldest auto-saved memory is replaced at the limit", async () => {
    renderSetting({ load: vi.fn().mockResolvedValue({ enabled: true }) });

    const toggle = await screen.findByRole("switch", { name: "チャットからの自動保存" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText("チャットから自動で記憶する")).toBeInTheDocument();
    expect(
      screen.getByText(
        "有効にすると、チャットの内容から覚えておく価値のあるものを自動で記憶に保存します。保存した内容はこの画面で確認・編集・無効化できます。上限（200件）に達すると、長く話題に出ていない記憶から自動で入れ替わります（自分で書いたり編集した記憶は対象外で、入れ替わった記憶は「無効化済み」から戻せます）。",
      ),
    ).toBeInTheDocument();
  });

  it("shows a disabled setting as off and explicitly enables it", async () => {
    let resolveUpdate: ((value: { enabled: boolean }) => void) | undefined;
    const update = vi.fn().mockImplementation(
      () =>
        new Promise<{ enabled: boolean }>((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    renderSetting({ update });

    const toggle = await screen.findByRole("switch", { name: "チャットからの自動保存" });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(toggle);

    await waitFor(() => expect(update).toHaveBeenCalledWith({ enabled: true }));
    expect(toggle).toBeDisabled();
    resolveUpdate?.({ enabled: true });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("reports setting update errors and keeps the setting off", async () => {
    const update = vi.fn().mockRejectedValue(new Error("設定を更新できませんでした。"));
    renderSetting({ update });

    const toggle = await screen.findByRole("switch", { name: "チャットからの自動保存" });
    fireEvent.click(toggle);

    expect(await screen.findByRole("alert")).toHaveTextContent("設定を更新できませんでした。");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).not.toBeDisabled();
  });

  it("disables the switch and reports the error when the setting cannot be loaded", async () => {
    renderSetting({ load: vi.fn().mockRejectedValue(new Error("設定を取得できませんでした。")) });

    expect(await screen.findByRole("alert")).toHaveTextContent("設定を取得できませんでした。");
    expect(screen.getByRole("switch", { name: "チャットからの自動保存" })).toBeDisabled();
  });
});
