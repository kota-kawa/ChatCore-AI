import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ContextPortabilityModal,
  MAX_CONTEXT_IMPORT_FILE_BYTES,
  validateContextImportFile,
} from "../components/memo/ContextPortabilityModal";

function renderModal(overrides: Partial<Parameters<typeof ContextPortabilityModal>[0]> = {}) {
  const api = {
    exportVault: vi.fn().mockResolvedValue({
      blob: new Blob(["portable"]),
      filename: "context.json",
    }),
    previewImport: vi.fn(),
    confirmImport: vi.fn(),
    ...overrides.api,
  };
  const onClose = overrides.onClose ?? vi.fn();
  const onImported = overrides.onImported ?? vi.fn();
  render(
    <ContextPortabilityModal
      isOpen
      onClose={onClose}
      onImported={onImported}
      {...overrides}
      api={api}
    />,
  );
  return { api, onClose, onImported };
}

function readableFile(content: string, name: string) {
  const file = new File([content], name, { type: "application/octet-stream" });
  Object.defineProperty(file, "text", {
    configurable: true,
    value: vi.fn().mockResolvedValue(content),
  });
  return file;
}

describe("ContextPortabilityModal", () => {
  it("validates supported extensions, empty files, and the 10MB limit", () => {
    expect(validateContextImportFile({ name: "vault.json", size: 1 })).toEqual({
      valid: true,
      format: "json",
    });
    expect(validateContextImportFile({ name: "vault.markdown", size: 1 })).toEqual({
      valid: true,
      format: "markdown",
    });
    expect(validateContextImportFile({ name: "vault.txt", size: 1 })).toMatchObject({
      valid: false,
    });
    expect(validateContextImportFile({ name: "vault.json", size: 0 })).toMatchObject({
      valid: false,
    });
    expect(
      validateContextImportFile({
        name: "vault.json",
        size: MAX_CONTEXT_IMPORT_FILE_BYTES + 1,
      }),
    ).toEqual({
      valid: false,
      message: "ファイルサイズは10MB以下にしてください。",
    });
  });

  it("downloads the selected export format", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:context-export");
    const revokeObjectURL = vi.fn();
    const clickAnchor = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const { api } = renderModal();

    try {
      fireEvent.click(screen.getByRole("radio", { name: /Markdown/ }));
      fireEvent.click(screen.getByRole("button", { name: "ダウンロード" }));

      await waitFor(() => expect(api.exportVault).toHaveBeenCalledWith("markdown"));
      expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
      expect(clickAnchor).toHaveBeenCalled();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:context-export");
    } finally {
      clickAnchor.mockRestore();
    }
  });

  it("rejects an unsupported file before calling the preview API", async () => {
    const { api } = renderModal();
    fireEvent.click(screen.getByRole("tab", { name: /取り込み/ }));
    fireEvent.change(screen.getByLabelText("インポートするファイル"), {
      target: { files: [readableFile("plain", "vault.txt")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("JSON（.json）またはMarkdown");
    expect(api.previewImport).not.toHaveBeenCalled();
  });

  it("keeps the modal open and reports export API errors", async () => {
    renderModal({
      api: {
        exportVault: vi.fn().mockRejectedValue(new Error("書き出しに失敗しました。")),
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "ダウンロード" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("書き出しに失敗しました。");
    expect(
      screen.getByRole("dialog", { name: "コンテキストの持ち運び" }),
    ).toBeInTheDocument();
  });

  it("previews warnings and samples, then imports only after explicit confirmation", async () => {
    const preview = {
      preview_token: "signed-preview-token",
      total_count: 3,
      active_count: 2,
      deprecated_count: 0,
      duplicate_count: 1,
      importable_count: 2,
      can_import: true,
      sample_facts: [
        {
          fact_type: "project",
          title: "移行計画",
          content: '<img src="https://example.com/tracker.png"> [外部リンク](https://example.com)',
          status: "active",
          importance: 75,
        },
      ],
      warnings: ["1件は既存データと重複するためスキップします。"],
      expires_at: "2026-07-23T13:00:00Z",
    };
    const imported = {
      status: "success",
      imported_count: 2,
      skipped_duplicate_count: 1,
      active_count: 2,
      deprecated_count: 0,
    };
    const previewImport = vi.fn().mockResolvedValue(preview);
    const confirmImport = vi.fn().mockResolvedValue(imported);
    const onImported = vi.fn();
    renderModal({ api: { previewImport, confirmImport }, onImported });

    fireEvent.click(screen.getByRole("tab", { name: /取り込み/ }));
    const content = '{"version":1,"facts":[]}';
    fireEvent.change(screen.getByLabelText("インポートするファイル"), {
      target: { files: [readableFile(content, "vault.json")] },
    });

    await screen.findByText("vault.json");
    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));

    await waitFor(() =>
      expect(previewImport).toHaveBeenCalledWith({ format: "json", content }),
    );
    expect(await screen.findByText("移行計画")).toBeInTheDocument();
    expect(screen.getByText(/重複するためスキップ/)).toBeInTheDocument();
    expect(screen.getByText(/<img src=/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "外部リンク" })).not.toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: "確認してインポート" });
    expect(confirmButton).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /プレビューと警告を確認しました/ }));
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(confirmImport).toHaveBeenCalledWith({
        format: "json",
        content,
        preview_token: "signed-preview-token",
      }),
    );
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    expect(await screen.findByText("インポートが完了しました")).toBeInTheDocument();
    expect(screen.getByText(/2件を追加し、1件の重複/)).toBeInTheDocument();
  });

  it("keeps a successful import result when refreshing the list fails", async () => {
    const content = '{"version":1,"facts":[]}';
    const previewImport = vi.fn().mockResolvedValue({
      preview_token: "signed-preview-token",
      total_count: 1,
      active_count: 1,
      deprecated_count: 0,
      duplicate_count: 0,
      importable_count: 1,
      can_import: true,
      sample_facts: [],
      warnings: [],
      expires_at: "2026-07-23T13:00:00Z",
    });
    const confirmImport = vi.fn().mockResolvedValue({
      status: "success",
      imported_count: 1,
      skipped_duplicate_count: 0,
      active_count: 1,
      deprecated_count: 0,
    });
    renderModal({
      api: { previewImport, confirmImport },
      onImported: vi.fn().mockRejectedValue(new Error("refresh failed")),
    });

    fireEvent.click(screen.getByRole("tab", { name: /取り込み/ }));
    fireEvent.change(screen.getByLabelText("インポートするファイル"), {
      target: { files: [readableFile(content, "vault.json")] },
    });
    await screen.findByText("vault.json");
    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));
    await screen.findByRole("checkbox", { name: /プレビューと警告を確認しました/ });
    fireEvent.click(screen.getByRole("checkbox", { name: /プレビューと警告を確認しました/ }));
    fireEvent.click(screen.getByRole("button", { name: "確認してインポート" }));

    expect(await screen.findByText("インポートが完了しました")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "インポートは完了しましたが、一覧を更新できませんでした。",
    );
    expect(confirmImport).toHaveBeenCalledTimes(1);
  });

  it("keeps confirmation disabled when the backend marks the preview as non-importable", async () => {
    const previewImport = vi.fn().mockResolvedValue({
      preview_token: "blocked-preview",
      total_count: 1,
      active_count: 1,
      deprecated_count: 0,
      duplicate_count: 0,
      importable_count: 1,
      can_import: false,
      sample_facts: [],
      warnings: ["インポートすると有効なコンテキストが200件を超えます。"],
      expires_at: "2026-07-23T13:00:00Z",
    });
    renderModal({ api: { previewImport } });
    fireEvent.click(screen.getByRole("tab", { name: /取り込み/ }));
    fireEvent.change(screen.getByLabelText("インポートするファイル"), {
      target: { files: [readableFile('{"facts":[]}', "vault.json")] },
    });
    await screen.findByText("vault.json");
    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));

    expect(
      await screen.findByText("インポートすると有効なコンテキストが200件を超えます。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /プレビューと警告を確認しました/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "確認してインポート" })).toBeDisabled();
  });

  it("closes with Escape and restores body scrolling", async () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
