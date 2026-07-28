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
  type ContextVaultExportFormat,
  type ContextVaultImportPreview,
  type ContextVaultImportResult,
} from "../../lib/memo/context_types";
import { useTranslation } from "../../contexts/locale_context";
import { jaMessages, type MessageKey } from "../../lib/i18n/catalogs/ja";

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

export function validateContextImportFile(
  file: Pick<File, "name" | "size">,
  translate: (key: MessageKey) => string = (key) => jaMessages[key],
): ImportFileValidation {
  const lowerName = file.name.toLowerCase();
  const format: ContextVaultExportFormat | null = lowerName.endsWith(".json")
    ? "json"
    : lowerName.endsWith(".md") || lowerName.endsWith(".markdown")
      ? "markdown"
      : null;
  if (!format) {
    return { valid: false, message: translate("memo.importFileTypeError") };
  }
  if (file.size === 0) {
    return { valid: false, message: translate("memo.importEmptyFileError") };
  }
  if (file.size > MAX_CONTEXT_IMPORT_FILE_BYTES) {
    return { valid: false, message: translate("memo.importFileSizeError") };
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
  const { t } = useTranslation();
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
      setErrorText(error instanceof Error ? error.message : t("memo.exportContextFailed"));
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

    const validation = validateContextImportFile(file, t);
    if (!validation.valid) {
      setErrorText(validation.message);
      event.target.value = "";
      return;
    }

    try {
      const content = await file.text();
      setSelectedImport({ name: file.name, format: validation.format, content });
    } catch {
      setErrorText(t("memo.readImportFileFailed"));
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
      setErrorText(error instanceof Error ? error.message : t("memo.previewImportFailed"));
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
          t("memo.importRefreshFailed"),
        );
      }
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : t("memo.importContextFailed"));
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
            <h2 id="context-portability-title">{t("memo.portabilityTitle")}</h2>
            <p id="context-portability-description">
              {t("memo.portabilityDescription")}
            </p>
          </div>
          <button
            type="button"
            className="memo-context-modal__close"
            aria-label={t("common.close")}
            onClick={close}
            disabled={busy}
          >
            <i className="bi bi-x-lg" aria-hidden="true" />
          </button>
        </header>

        <div className="memo-context-portability__tabs" role="tablist" aria-label={t("memo.actions")}>
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
            {t("memo.exportAction")}
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
            {t("memo.importAction")}
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
              <legend>{t("memo.fileFormat")}</legend>
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
                  {t("memo.jsonFormatDescription")}
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
                  {t("memo.markdownFormatDescription")}
                </span>
              </label>
            </fieldset>
            <div className="memo-context-portability__actions">
              <button type="button" className="is-primary" onClick={handleExport} disabled={busy}>
                <i className="bi bi-download" aria-hidden="true" />
                {busy ? t("memo.preparing") : t("memo.download")}
              </button>
              <button type="button" onClick={close} disabled={busy}>{t("common.cancel")}</button>
            </div>
          </div>
        ) : (
          <div className="memo-context-portability__section" role="tabpanel">
            {importResult ? (
              <div className="memo-context-portability__result" role="status">
                <i className="bi bi-check-circle" aria-hidden="true" />
                <h3>{t("memo.importComplete")}</h3>
                <p>
                  {t("memo.importResult", { imported: importResult.imported_count, skipped: importResult.skipped_duplicate_count })}
                </p>
                <dl>
                  <div><dt>{t("memo.active")}</dt><dd>{t("memo.items", { count: importResult.active_count })}</dd></div>
                  <div><dt>{t("memo.deprecated")}</dt><dd>{t("memo.items", { count: importResult.deprecated_count })}</dd></div>
                </dl>
                <button type="button" className="is-primary" onClick={close}>{t("common.close")}</button>
              </div>
            ) : (
              <>
                <div className="memo-context-portability__file">
                  <label htmlFor="context-import-file">{t("memo.importFile")}</label>
                  <input
                    ref={fileInputRef}
                    id="context-import-file"
                    type="file"
                    accept=".json,.md,.markdown,application/json,text/markdown"
                    onChange={(event) => void handleFileChange(event)}
                    disabled={busy}
                  />
                  <p>
                    {t("memo.importFileHelp")}
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
                      {busy ? t("memo.checking") : t("memo.reviewContent")}
                    </button>
                    <button type="button" onClick={close} disabled={busy}>{t("common.cancel")}</button>
                  </div>
                ) : (
                  <div className="memo-context-portability__preview">
                    <div className="memo-context-portability__summary" aria-label={t("memo.importReview")}>
                      <div><strong>{preview.importable_count}</strong><span>{t("memo.toAdd")}</span></div>
                      <div><strong>{preview.duplicate_count}</strong><span>{t("memo.duplicateSkip")}</span></div>
                      <div><strong>{preview.active_count}</strong><span>{t("memo.active")}</span></div>
                      <div><strong>{preview.deprecated_count}</strong><span>{t("memo.deprecated")}</span></div>
                    </div>

                    {(preview.warnings.length > 0 || !preview.can_import) && (
                      <div className="memo-context-portability__warnings" role="alert">
                        <h3><i className="bi bi-exclamation-triangle" aria-hidden="true" />{t("memo.reviewNotes")}</h3>
                        <ul>
                          {!preview.can_import && preview.warnings.length === 0 && (
                            <li>{t("memo.cannotImport")}</li>
                          )}
                          {preview.warnings.map((warning, index) => (
                            <li key={`${index}-${warning}`}>{warning}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {preview.sample_facts.length > 0 && (
                      <div className="memo-context-portability__samples">
                        <h3>{t("memo.importSamples")}</h3>
                        <ul>
                          {preview.sample_facts.map((fact, index) => (
                            <li key={`${index}-${fact.fact_type}-${fact.title}`}>
                              <div>
                                <span>{t(`memo.factType${fact.fact_type.charAt(0).toUpperCase()}${fact.fact_type.slice(1)}` as MessageKey)}</span>
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
                        {t("memo.importConfirmation", { count: preview.importable_count })}
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
                        {busy ? t("memo.importing") : t("memo.confirmImport")}
                      </button>
                      <button type="button" onClick={resetImport} disabled={busy}>{t("memo.chooseAnotherFile")}</button>
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
