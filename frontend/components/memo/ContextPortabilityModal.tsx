import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import { useModalFocusTrap } from "../../hooks/use_modal_focus_trap";
import {
  confirmContextVaultImport as defaultConfirmImport,
  exportContextVault as defaultExport,
  previewContextVaultImport as defaultPreviewImport,
} from "../../lib/memo/context_api";
import {
  CONTEXT_FACT_TYPE_LABELS,
  type ContextVaultExportFormat,
  type ContextVaultImportPreview,
  type ContextVaultImportResult,
} from "../../lib/memo/context_types";

export const MAX_CONTEXT_IMPORT_FILE_BYTES = 10 * 1024 * 1024;

export type ContextPortabilityApi = {
  exportVault: typeof defaultExport;
  previewImport: typeof defaultPreviewImport;
  confirmImport: typeof defaultConfirmImport;
};

type ContextPortabilityModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onImported: () => void | Promise<void>;
  api?: Partial<ContextPortabilityApi>;
};

type SelectedImport = {
  name: string;
  format: ContextVaultExportFormat;
  content: string;
};

type ImportFileValidation =
  | { valid: true; format: ContextVaultExportFormat }
  | { valid: false; message: string };

export function validateContextImportFile(file: Pick<File, "name" | "size">): ImportFileValidation {
  const lowerName = file.name.toLowerCase();
  const format: ContextVaultExportFormat | null = lowerName.endsWith(".json")
    ? "json"
    : lowerName.endsWith(".md") || lowerName.endsWith(".markdown")
      ? "markdown"
      : null;
  if (!format) {
    return { valid: false, message: "JSON（.json）またはMarkdown（.md / .markdown）ファイルを選択してください。" };
  }
  if (file.size === 0) {
    return { valid: false, message: "空のファイルはインポートできません。" };
  }
  if (file.size > MAX_CONTEXT_IMPORT_FILE_BYTES) {
    return { valid: false, message: "ファイルサイズは10MB以下にしてください。" };
  }
  return { valid: true, format };
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function ContextPortabilityModal({
  isOpen,
  onClose,
  onImported,
  api,
}: ContextPortabilityModalProps) {
  const exportVault = api?.exportVault ?? defaultExport;
  const previewImport = api?.previewImport ?? defaultPreviewImport;
  const confirmImport = api?.confirmImport ?? defaultConfirmImport;

  const [view, setView] = useState<"export" | "import">("export");
  const [exportFormat, setExportFormat] = useState<ContextVaultExportFormat>("json");
  const [selectedImport, setSelectedImport] = useState<SelectedImport | null>(null);
  const [preview, setPreview] = useState<ContextVaultImportPreview | null>(null);
  const [importResult, setImportResult] = useState<ContextVaultImportResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorText, setErrorText] = useState("");
  const dialogRef = useRef<HTMLElement | null>(null);
  const initialFocusRef = useRef<HTMLButtonElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const resetImport = useCallback(() => {
    setSelectedImport(null);
    setPreview(null);
    setImportResult(null);
    setConfirmed(false);
    setErrorText("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  useEffect(() => {
    if (isOpen) return;
    setView("export");
    setExportFormat("json");
    setBusy(false);
    resetImport();
  }, [isOpen, resetImport]);

  const close = useCallback(() => {
    if (!busy) onClose();
  }, [busy, onClose]);

  const getInitialFocus = useCallback(
    () => initialFocusRef.current ?? dialogRef.current,
    [],
  );

  useModalFocusTrap({
    isOpen,
    containerRef: dialogRef,
    getInitialFocus,
    onEscape: close,
  });
  useBodyScrollLock(isOpen);

  const switchView = (nextView: "export" | "import") => {
    if (busy) return;
    setView(nextView);
    setErrorText("");
  };

  const handleExport = async () => {
    setBusy(true);
    setErrorText("");
    try {
      const exported = await exportVault(exportFormat);
      downloadBlob(exported.blob, exported.filename);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "コンテキストを書き出せませんでした。");
    } finally {
      setBusy(false);
    }
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setPreview(null);
    setImportResult(null);
    setConfirmed(false);
    setErrorText("");
    setSelectedImport(null);
    if (!file) return;

    const validation = validateContextImportFile(file);
    if (!validation.valid) {
      setErrorText(validation.message);
      event.target.value = "";
      return;
    }

    try {
      const content = await file.text();
      setSelectedImport({ name: file.name, format: validation.format, content });
    } catch {
      setErrorText("ファイルを読み込めませんでした。別のファイルを選択してください。");
      event.target.value = "";
    }
  };

  const handlePreview = async () => {
    if (!selectedImport) return;
    setBusy(true);
    setErrorText("");
    setPreview(null);
    setImportResult(null);
    setConfirmed(false);
    try {
      setPreview(
        await previewImport({
          format: selectedImport.format,
          content: selectedImport.content,
        }),
      );
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "インポート内容を確認できませんでした。");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmImport = async () => {
    if (
      !selectedImport ||
      !preview ||
      !confirmed ||
      !preview.can_import ||
      preview.importable_count === 0
    ) {
      return;
    }
    setBusy(true);
    setErrorText("");
    try {
      const result = await confirmImport({
        format: selectedImport.format,
        content: selectedImport.content,
        preview_token: preview.preview_token,
      });
      setImportResult(result);
      setPreview(null);
      setConfirmed(false);
      try {
        await onImported();
      } catch {
        setErrorText(
          "インポートは完了しましたが、一覧を更新できませんでした。ページを再読み込みしてください。",
        );
      }
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "コンテキストをインポートできませんでした。");
    } finally {
      setBusy(false);
    }
  };

  if (!isOpen || typeof document === "undefined") return null;

  return createPortal(
    <div className="memo-context-modal">
      <div className="memo-context-modal__overlay" onClick={close} aria-hidden="true" />
      <section
        ref={dialogRef}
        className="memo-context-modal__content memo-context-portability"
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-portability-title"
        aria-describedby="context-portability-description"
        aria-busy={busy}
        tabIndex={-1}
      >
        <header className="memo-context-modal__header">
          <div>
            <h2 id="context-portability-title">コンテキストの持ち運び</h2>
            <p id="context-portability-description">
              金庫の内容をJSON・Markdownで書き出し、別の環境から安全に取り込めます。
            </p>
          </div>
          <button
            type="button"
            className="memo-context-modal__close"
            aria-label="閉じる"
            onClick={close}
            disabled={busy}
          >
            <i className="bi bi-x-lg" aria-hidden="true" />
          </button>
        </header>

        <div className="memo-context-portability__tabs" role="tablist" aria-label="操作">
          <button
            ref={initialFocusRef}
            type="button"
            role="tab"
            aria-selected={view === "export"}
            className={view === "export" ? "is-active" : ""}
            onClick={() => switchView("export")}
            disabled={busy}
          >
            <i className="bi bi-download" aria-hidden="true" />
            書き出し
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "import"}
            className={view === "import" ? "is-active" : ""}
            onClick={() => switchView("import")}
            disabled={busy}
          >
            <i className="bi bi-upload" aria-hidden="true" />
            取り込み
          </button>
        </div>

        {errorText && (
          <div className="memo-flash memo-flash--error" role="alert">
            {errorText}
          </div>
        )}

        {view === "export" ? (
          <div className="memo-context-portability__section" role="tabpanel">
            <fieldset className="memo-context-portability__format">
              <legend>ファイル形式</legend>
              <label className={exportFormat === "json" ? "is-active" : ""}>
                <input
                  type="radio"
                  name="context-export-format"
                  value="json"
                  checked={exportFormat === "json"}
                  onChange={() => setExportFormat("json")}
                  disabled={busy}
                />
                <span>
                  <strong>JSON</strong>
                  再インポートや機械処理に適した完全なデータ
                </span>
              </label>
              <label className={exportFormat === "markdown" ? "is-active" : ""}>
                <input
                  type="radio"
                  name="context-export-format"
                  value="markdown"
                  checked={exportFormat === "markdown"}
                  onChange={() => setExportFormat("markdown")}
                  disabled={busy}
                />
                <span>
                  <strong>Markdown</strong>
                  人が読みやすく、他のノートにも移しやすい形式
                </span>
              </label>
            </fieldset>
            <div className="memo-context-portability__actions">
              <button type="button" className="is-primary" onClick={handleExport} disabled={busy}>
                <i className="bi bi-download" aria-hidden="true" />
                {busy ? "準備中…" : "ダウンロード"}
              </button>
              <button type="button" onClick={close} disabled={busy}>キャンセル</button>
            </div>
          </div>
        ) : (
          <div className="memo-context-portability__section" role="tabpanel">
            {importResult ? (
              <div className="memo-context-portability__result" role="status">
                <i className="bi bi-check-circle" aria-hidden="true" />
                <h3>インポートが完了しました</h3>
                <p>
                  {importResult.imported_count}件を追加し、
                  {importResult.skipped_duplicate_count}件の重複をスキップしました。
                </p>
                <dl>
                  <div><dt>有効</dt><dd>{importResult.active_count}件</dd></div>
                  <div><dt>無効化済み</dt><dd>{importResult.deprecated_count}件</dd></div>
                </dl>
                <button type="button" className="is-primary" onClick={close}>閉じる</button>
              </div>
            ) : (
              <>
                <div className="memo-context-portability__file">
                  <label htmlFor="context-import-file">インポートするファイル</label>
                  <input
                    ref={fileInputRef}
                    id="context-import-file"
                    type="file"
                    accept=".json,.md,.markdown,application/json,text/markdown"
                    onChange={(event) => void handleFileChange(event)}
                    disabled={busy}
                  />
                  <p>
                    Chat-Coreから書き出したJSONまたはMarkdown（10MB以下）を選択してください。
                    既存の事実は上書きしません。
                  </p>
                  {selectedImport && (
                    <p className="memo-context-portability__selected-file">
                      <i className="bi bi-file-earmark-check" aria-hidden="true" />
                      {selectedImport.name}
                    </p>
                  )}
                </div>

                {!preview ? (
                  <div className="memo-context-portability__actions">
                    <button
                      type="button"
                      className="is-primary"
                      onClick={handlePreview}
                      disabled={!selectedImport || busy}
                    >
                      {busy ? "確認中…" : "内容を確認"}
                    </button>
                    <button type="button" onClick={close} disabled={busy}>キャンセル</button>
                  </div>
                ) : (
                  <div className="memo-context-portability__preview">
                    <div className="memo-context-portability__summary" aria-label="インポート確認">
                      <div><strong>{preview.importable_count}</strong><span>追加予定</span></div>
                      <div><strong>{preview.duplicate_count}</strong><span>重複スキップ</span></div>
                      <div><strong>{preview.active_count}</strong><span>有効</span></div>
                      <div><strong>{preview.deprecated_count}</strong><span>無効化済み</span></div>
                    </div>

                    {(preview.warnings.length > 0 || !preview.can_import) && (
                      <div className="memo-context-portability__warnings" role="alert">
                        <h3><i className="bi bi-exclamation-triangle" aria-hidden="true" />確認事項</h3>
                        <ul>
                          {!preview.can_import && preview.warnings.length === 0 && (
                            <li>この内容はインポートできません。ファイル内容と保存上限を確認してください。</li>
                          )}
                          {preview.warnings.map((warning, index) => (
                            <li key={`${index}-${warning}`}>{warning}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {preview.sample_facts.length > 0 && (
                      <div className="memo-context-portability__samples">
                        <h3>追加される事実のサンプル</h3>
                        <ul>
                          {preview.sample_facts.map((fact, index) => (
                            <li key={`${index}-${fact.fact_type}-${fact.title}`}>
                              <div>
                                <span>{CONTEXT_FACT_TYPE_LABELS[fact.fact_type]}</span>
                                <strong>{fact.title}</strong>
                              </div>
                              <p className="memo-context-portability__sample-content">
                                {fact.content}
                              </p>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <label className="memo-context-portability__confirmation">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(event) => setConfirmed(event.target.checked)}
                        disabled={busy || !preview.can_import || preview.importable_count === 0}
                      />
                      <span>
                        プレビューと警告を確認しました。既存データを変更せず、
                        {preview.importable_count}件を追加します。
                      </span>
                    </label>

                    <div className="memo-context-portability__actions">
                      <button
                        type="button"
                        className="is-primary"
                        onClick={handleConfirmImport}
                        disabled={
                          !confirmed ||
                          !preview.can_import ||
                          preview.importable_count === 0 ||
                          busy
                        }
                      >
                        {busy ? "取り込み中…" : "確認してインポート"}
                      </button>
                      <button type="button" onClick={resetImport} disabled={busy}>別のファイルを選ぶ</button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </section>
    </div>,
    document.body,
  );
}
