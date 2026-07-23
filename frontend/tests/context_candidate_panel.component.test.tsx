import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import {
  ContextCandidatePanel,
  type ContextCandidateApi,
} from "../components/memo/ContextCandidatePanel";
import type { ContextFactCandidate } from "../lib/memo/context_types";

const sampleCandidate: ContextFactCandidate = {
  id: 21,
  fact_type: "preference",
  title: "回答の好み",
  content: "回答は簡潔な日本語にする",
  importance: 50,
  confidence: 0.86,
  status: "pending",
  revision: 3,
  source_kind: "chat",
  source_ref: "chat:42",
  created_at: null,
  updated_at: null,
};

const secondCandidate: ContextFactCandidate = {
  ...sampleCandidate,
  id: 22,
  fact_type: "project",
  title: "移行プロジェクト",
  content: "API互換性を維持して段階移行する",
  confidence: 72,
  revision: 1,
};

function renderCandidatePanel({
  api,
  onApproved,
}: {
  api?: Partial<ContextCandidateApi>;
  onApproved?: () => void | Promise<unknown>;
} = {}) {
  const completeApi: ContextCandidateApi = {
    load: vi.fn().mockResolvedValue({ candidates: [], totalPending: 0, nextCursor: null }),
    approve: vi.fn().mockResolvedValue(null),
    reject: vi.fn().mockResolvedValue(undefined),
    loadSettings: vi.fn().mockResolvedValue({ enabled: false }),
    updateSettings: vi.fn().mockImplementation(async ({ enabled }) => ({ enabled })),
    ...api,
  };

  return {
    ...render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <ContextCandidatePanel api={completeApi} onApproved={onApproved} />
      </SWRConfig>,
    ),
    api: completeApi,
  };
}

describe("ContextCandidatePanel", () => {
  it("shows the pending count and candidate metadata", async () => {
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 4,
          nextCursor: null,
        }),
      },
    });

    expect(await screen.findByText(sampleCandidate.title)).toBeInTheDocument();
    expect(screen.getByLabelText("保留中 4件")).toHaveTextContent("4");
    expect(screen.getByText("確信度 86%")).toBeInTheDocument();
    expect(screen.getByText("出典: チャット")).toBeInTheDocument();
  });

  it("keeps automatic extraction off by default and explicitly enables it", async () => {
    let resolveUpdate: ((value: { enabled: boolean }) => void) | undefined;
    const updateSettings = vi.fn().mockImplementation(
      () =>
        new Promise<{ enabled: boolean }>((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    renderCandidatePanel({ api: { updateSettings } });

    const toggle = await screen.findByRole("switch", { name: "チャットからの自動抽出" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(
      screen.getByText(
        "有効にすると、今後のチャットから保存候補を非同期で提案します。候補は承認するまで金庫に保存されません",
      ),
    ).toBeInTheDocument();

    fireEvent.click(toggle);

    await waitFor(() => expect(updateSettings).toHaveBeenCalledWith({ enabled: true }));
    expect(toggle).toBeDisabled();
    resolveUpdate?.({ enabled: true });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("reports extraction setting update errors and keeps opt-in disabled", async () => {
    const updateSettings = vi.fn().mockRejectedValue(new Error("設定を更新できませんでした。"));
    renderCandidatePanel({ api: { updateSettings } });

    const toggle = await screen.findByRole("switch", { name: "チャットからの自動抽出" });
    fireEvent.click(toggle);

    expect(await screen.findByRole("alert")).toHaveTextContent("設定を更新できませんでした。");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).not.toBeDisabled();
  });

  it("approves with the current revision and refreshes the fact list", async () => {
    const load = vi.fn().mockResolvedValue({
      candidates: [sampleCandidate],
      totalPending: 1,
      nextCursor: null,
    });
    const approve = vi.fn().mockResolvedValue(null);
    const onApproved = vi.fn().mockResolvedValue(undefined);
    renderCandidatePanel({ api: { load, approve }, onApproved });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "承認" }));

    await waitFor(() =>
      expect(approve).toHaveBeenCalledWith(sampleCandidate.id, {
        revision: sampleCandidate.revision,
      }),
    );
    await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
  });

  it("edits a candidate in an accessible modal before approval", async () => {
    const approve = vi.fn().mockResolvedValue(null);
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 1,
          nextCursor: null,
        }),
        approve,
      },
    });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "編集して承認" }));
    expect(screen.getByRole("dialog", { name: "提案を編集して承認" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.change(screen.getByLabelText("タイトル"), { target: { value: "更新した決定" } });
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "互換性を優先する" } });
    fireEvent.change(screen.getByLabelText("重要度"), { target: { value: "75" } });
    fireEvent.click(screen.getByRole("button", { name: "候補の種類" }));
    fireEvent.click(screen.getByRole("option", { name: "過去の決定" }));
    fireEvent.click(screen.getByRole("button", { name: "この内容で承認" }));

    await waitFor(() =>
      expect(approve).toHaveBeenCalledWith(sampleCandidate.id, {
        revision: sampleCandidate.revision,
        fact_type: "decision",
        title: "更新した決定",
        content: "互換性を優先する",
        importance: 75,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "提案を編集して承認" })).not.toBeInTheDocument(),
    );
    expect(document.body.style.overflow).toBe("");
  });

  it("confirms rejection in a modal and sends the revision", async () => {
    const reject = vi.fn().mockResolvedValue(undefined);
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 1,
          nextCursor: null,
        }),
        reject,
      },
    });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "却下" }));
    expect(screen.getByRole("dialog", { name: "提案を却下" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "却下する" }));

    await waitFor(() =>
      expect(reject).toHaveBeenCalledWith(sampleCandidate.id, {
        revision: sampleCandidate.revision,
      }),
    );
  });

  it("shows approval failures inside the active modal", async () => {
    const approve = vi.fn().mockRejectedValue(new Error("候補のrevisionが競合しています。"));
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 1,
          nextCursor: null,
        }),
        approve,
      },
    });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "編集して承認" }));
    const dialog = screen.getByRole("dialog", { name: "提案を編集して承認" });
    fireEvent.click(within(dialog).getByRole("button", { name: "この内容で承認" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "候補のrevisionが競合しています。",
    );
  });

  it("validates importance before submitting an edited approval", async () => {
    const approve = vi.fn().mockResolvedValue(null);
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 1,
          nextCursor: null,
        }),
        approve,
      },
    });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "編集して承認" }));
    const dialog = screen.getByRole("dialog", { name: "提案を編集して承認" });
    fireEvent.change(within(dialog).getByLabelText("重要度"), { target: { value: "101" } });
    const form = dialog.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "重要度は0から100の範囲で入力してください。",
    );
    expect(approve).not.toHaveBeenCalled();
  });

  it("loads cursor pages and removes duplicate candidate ids", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({
        candidates: [sampleCandidate],
        totalPending: 2,
        nextCursor: "candidate-cursor",
      })
      .mockResolvedValueOnce({
        candidates: [sampleCandidate, secondCandidate, secondCandidate],
        totalPending: 2,
        nextCursor: null,
      });
    renderCandidatePanel({ api: { load } });

    const loadMore = await screen.findByRole("button", { name: "提案をさらに読み込む" });
    fireEvent.click(loadMore);

    await screen.findByText(secondCandidate.title);
    expect(screen.getAllByText(sampleCandidate.title)).toHaveLength(1);
    expect(screen.getAllByText(secondCandidate.title)).toHaveLength(1);
    expect(load).toHaveBeenNthCalledWith(2, {
      status: "pending",
      limit: 20,
      cursor: "candidate-cursor",
    });
  });

  it("keeps a candidate available and reports approval errors", async () => {
    const approve = vi.fn().mockRejectedValue(new Error("候補のrevisionが競合しています。"));
    renderCandidatePanel({
      api: {
        load: vi.fn().mockResolvedValue({
          candidates: [sampleCandidate],
          totalPending: 1,
          nextCursor: null,
        }),
        approve,
      },
    });

    await screen.findByText(sampleCandidate.title);
    fireEvent.click(screen.getByRole("button", { name: "承認" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("候補のrevisionが競合しています。");
    expect(screen.getByText(sampleCandidate.title)).toBeInTheDocument();
  });
});
