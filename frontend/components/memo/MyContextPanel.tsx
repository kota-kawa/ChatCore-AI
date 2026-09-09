import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import {
  createContextFact as defaultCreate,
  loadContextFacts as defaultLoad,
  updateContextFact as defaultUpdate,
} from "../../lib/memo/context_api";
import {
  CONTEXT_FACT_IMPORTANCE_OPTIONS,
  CONTEXT_FACT_TYPE_OPTIONS,
  toContextFactImportancePreset,
  type ContextFact,
  type ContextFactImportancePreset,
  type ContextFactStatus,
  type ContextFactType,
} from "../../lib/memo/context_types";
import { MemoListSkeleton } from "./MemoListSkeleton";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import {
  ContextCandidatePanel,
  type ContextCandidateApi,
} from "./ContextCandidatePanel";
import {
  ContextPortabilityModal,
  type ContextPortabilityApi,
} from "./ContextPortabilityModal";
import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";

type ContextApi = {
  load: typeof defaultLoad;
  create: typeof defaultCreate;
  update: typeof defaultUpdate;
};

type MyContextPanelProps = {
  isLoggedIn: boolean;
  api?: Partial<ContextApi>;
  candidateApi?: Partial<ContextCandidateApi>;
  portabilityApi?: Partial<ContextPortabilityApi>;
};

type EditorState = {
  mode: "create" | "edit";
  factId: number | null;
  revision: number;
  factType: ContextFactType;
  importance: ContextFactImportancePreset;
  importanceDirty: boolean;
  title: string;
  content: string;
};

const EMPTY_EDITOR: EditorState = {
  mode: "create",
  factId: null,
  revision: 0,
  factType: "preference",
  importance: 50,
  importanceDirty: false,
  title: "",
  content: "",
};

export function MyContextPanel({
  isLoggedIn,
  api,
  candidateApi,
  portabilityApi,
}: MyContextPanelProps) {
  const { t } = useTranslation();
  const factTypeKeys: Record<ContextFactType, MessageKey> = {
    profile: "memo.factTypeProfile", preference: "memo.factTypePreference", project: "memo.factTypeProject",
    decision: "memo.factTypeDecision", reference: "memo.factTypeReference",
  };
  const localizedTypeOptions = CONTEXT_FACT_TYPE_OPTIONS.map((option) => ({ ...option, label: t(factTypeKeys[option.value as ContextFactType]) }));
  const importanceOptions = CONTEXT_FACT_IMPORTANCE_OPTIONS.map((option) => ({ ...option, label: option.value === "25" ? t("memo.importanceLow") : option.value === "75" ? t("memo.importanceHigh") : t("memo.importanceStandard") }));
  const sourceLabel = (source: string) => source === "manual" ? t("memo.sourceManual") : source === "chat" ? t("memo.sourceChat") : source === "import" ? t("memo.sourceImport") : source;
  const importanceLabel = (value: number) => value <= 33 ? t("memo.importanceLow") : value >= 67 ? t("memo.importanceHigh") : t("memo.importanceStandard");
  const load = api?.load ?? defaultLoad;
  const create = api?.create ?? defaultCreate;
  const update = api?.update ?? defaultUpdate;

  const [statusFilter, setStatusFilter] = useState<ContextFactStatus>("active");
  const [typeFilter, setTypeFilter] = useState<ContextFactType | "all">("all");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [busyFactId, setBusyFactId] = useState<number | null>(null);
  const [additionalFacts, setAdditionalFacts] = useState<ContextFact[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [isPortabilityOpen, setIsPortabilityOpen] = useState(false);
  const activeLoadMoreRef = useRef<string | null>(null);
  const activeFilterKeyRef = useRef<string | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);

  const swrKey = isLoggedIn ? `context-facts|${statusFilter}|${typeFilter}` : null;
  activeFilterKeyRef.current = swrKey;
  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () =>
      load({
        factType: typeFilter === "all" ? null : typeFilter,
        status: statusFilter,
      }),
    { revalidateOnFocus: false },
  );

  useEffect(() => {
    setAdditionalFacts([]);
    setNextCursor(data?.nextCursor ?? null);
    setLoadingMore(false);
    activeLoadMoreRef.current = null;
  }, [data, swrKey]);

  useEffect(() => {
    setErrorText(null);
  }, [swrKey]);

  const facts = useMemo(() => {
    const uniqueFacts = new Map<number, ContextFact>();
    for (const fact of [...(data?.facts ?? []), ...additionalFacts]) {
      if (!uniqueFacts.has(fact.id)) uniqueFacts.set(fact.id, fact);
    }
    return [...uniqueFacts.values()];
  }, [additionalFacts, data?.facts]);
  const totalActive = data?.totalActive ?? 0;

  const typeOptions = useMemo(
    () => [{ value: "all", label: t("memo.allTypes") }, ...localizedTypeOptions],
    [t],
  );

  const refreshFactsAfterCandidateApproval = useCallback(async () => {
    await mutate();
  }, [mutate]);

  const openCreate = () => {
    setErrorText(null);
    setEditor({ ...EMPTY_EDITOR });
  };

  const openEdit = (fact: ContextFact) => {
    setErrorText(null);
    setEditor({
      mode: "edit",
      factId: fact.id,
      revision: fact.revision,
      factType: fact.fact_type,
      importance: toContextFactImportancePreset(fact.importance),
      importanceDirty: false,
      title: fact.title,
      content: fact.content,
    });
  };

  const closeEditor = useCallback(() => {
    setEditor(null);
    setSubmitting(false);
    setErrorText(null);
  }, []);

  const getInitialModalFocus = useCallback(() => titleInputRef.current, []);

  // フォーカストラップと Escape は ModalShell が担う。スクロールロックだけをここで持つ。
  // ModalShell owns the focus trap and Escape; only the scroll lock lives here.
  useBodyScrollLock(editor !== null);

  const handleSubmit = async () => {
    if (!editor) return;
    if (!editor.title.trim() || !editor.content.trim()) {
      setErrorText(t("memo.titleContentRequired"));
      return;
    }
    setSubmitting(true);
    setErrorText(null);
    try {
      if (editor.mode === "create") {
        await create({
          fact_type: editor.factType,
          title: editor.title.trim(),
          content: editor.content.trim(),
          importance: editor.importance,
        });
      } else if (editor.factId !== null) {
        await update(editor.factId, {
          revision: editor.revision,
          fact_type: editor.factType,
          title: editor.title.trim(),
          content: editor.content.trim(),
          ...(editor.importanceDirty ? { importance: editor.importance } : {}),
        });
      }
      closeEditor();
      await mutate();
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : t("memo.saveFailed"));
      setSubmitting(false);
    }
  };

  const handleToggleStatus = async (fact: ContextFact) => {
    setBusyFactId(fact.id);
    setErrorText(null);
    try {
      await update(fact.id, {
        revision: fact.revision,
        status: fact.status === "active" ? "deprecated" : "active",
      });
      await mutate();
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : t("memo.statusChangeFailed"));
    } finally {
      setBusyFactId(null);
    }
  };

  const handleLoadMore = async () => {
    if (!nextCursor || loadingMore || activeLoadMoreRef.current) return;

    const requestedCursor = nextCursor;
    const requestedFilterKey = swrKey;
    activeLoadMoreRef.current = requestedCursor;
    setLoadingMore(true);
    setErrorText(null);
    try {
      const page = await load({
        factType: typeFilter === "all" ? null : typeFilter,
        status: statusFilter,
        cursor: requestedCursor,
      });
      if (activeFilterKeyRef.current !== requestedFilterKey) return;

      const knownIds = new Set(facts.map((fact) => fact.id));
      const newFacts: ContextFact[] = [];
      for (const fact of page.facts) {
        if (knownIds.has(fact.id)) continue;
        knownIds.add(fact.id);
        newFacts.push(fact);
      }
      setAdditionalFacts((currentFacts) => [...currentFacts, ...newFacts]);
      setNextCursor(page.nextCursor === requestedCursor ? null : page.nextCursor);
    } catch (err) {
      if (activeFilterKeyRef.current === requestedFilterKey) {
        setErrorText(err instanceof Error ? err.message : t("memo.loadMoreContextFailed"));
      }
    } finally {
      if (activeFilterKeyRef.current === requestedFilterKey) setLoadingMore(false);
      if (activeLoadMoreRef.current === requestedCursor) activeLoadMoreRef.current = null;
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="memo-context memo-context--guest">
        <div className="memo-context-empty">
          <i className="bi bi-safe" aria-hidden="true"></i>
          <h2 className="memo-context-empty__title">{t("memo.myContext")}</h2>
          <p className="memo-context-empty__text">{t("memo.contextGuestDescription")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="memo-context">
      <header className="memo-context__header">
        <div className="memo-context__heading">
          <h1 className="memo-context__title">{t("memo.myContext")}</h1>
          <p className="memo-context__subtitle">{t("memo.contextDescription", { count: totalActive })}</p>
        </div>
        <div className="memo-context__header-actions">
          <button
            type="button"
            className="memo-context__portability-btn"
            onClick={() => setIsPortabilityOpen(true)}
          >
            <i className="bi bi-arrow-left-right" aria-hidden="true" />
            <span>{t("memo.portability")}</span>
          </button>
          <button type="button" className="memo-context__add-btn" onClick={openCreate}>
            <i className="bi bi-plus-lg" aria-hidden="true"></i>
            <span>{t("memo.addContext")}</span>
          </button>
        </div>
      </header>

      <ContextPortabilityModal
        isOpen={isPortabilityOpen}
        onClose={() => setIsPortabilityOpen(false)}
        onImported={async () => {
          setAdditionalFacts([]);
          await mutate();
        }}
        api={portabilityApi}
      />

      <ContextCandidatePanel
        api={candidateApi}
        onApproved={refreshFactsAfterCandidateApproval}
      />

      <div className="memo-context__filters">
        <MemoSelect
          value={typeFilter}
          onChange={(v) => setTypeFilter(v as ContextFactType | "all")}
          options={typeOptions}
          className="memo-context__filter-select"
        />
        <div className="memo-context__status-toggle" role="group" aria-label={t("memo.statusFilter")}>
          <button
            type="button"
            className={`memo-context__status-btn${statusFilter === "active" ? " is-active" : ""}`}
            onClick={() => setStatusFilter("active")}
          >
            {t("memo.active")}
          </button>
          <button
            type="button"
            className={`memo-context__status-btn${statusFilter === "deprecated" ? " is-active" : ""}`}
            onClick={() => setStatusFilter("deprecated")}
          >
            {t("memo.deprecated")}
          </button>
        </div>
      </div>

      {errorText && editor === null && (
        <div className="memo-flash memo-flash--error" role="alert">
          {errorText}
        </div>
      )}

      {editor && (
        <ModalShell
          isOpen
          onClose={closeEditor}
          id="context-editor-modal"
          className="cc-modal memo-modal-scope memo-context-modal memo-context-editor"
          labelledBy="context-editor-title"
          dismissDisabled={submitting}
          getInitialFocus={getInitialModalFocus}
        >
          <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1} aria-busy={submitting}>
            <header className="cc-modal__header">
              <div className="cc-modal__heading">
                <h2 className="cc-modal__title" id="context-editor-title">
                  {editor.mode === "create" ? t("memo.addContext") : t("memo.editContext")}
                </h2>
                <p className="cc-modal__lead" id="context-editor-description">
                  {t("memo.contextEditorDescription")}
                </p>
              </div>
              <ModalCloseButton label={t("common.close")} onClick={closeEditor} disabled={submitting} />
            </header>
            <form
              className="cc-modal__form"
              onSubmit={(event) => {
                event.preventDefault();
                void handleSubmit();
              }}
            >
              <div className="cc-modal__body memo-context-editor__form">
                {errorText && (
                  <div className="cc-modal__notice memo-context-modal__error" role="alert">
                    {errorText}
                  </div>
                )}
                <div className="memo-context-editor__row">
                  <span className="memo-context-editor__label">{t("memo.type")}</span>
                  <MemoSelect
                    id="context-fact-type"
                    ariaLabel={t("memo.type")}
                    value={editor.factType}
                    onChange={(v) => setEditor({ ...editor, factType: v as ContextFactType })}
                    options={localizedTypeOptions}
                    className="memo-context-editor__select"
                  />
                  <span className="memo-context-editor__label">{t("memo.importance")}</span>
                  <MemoSelect
                    id="context-fact-importance"
                    ariaLabel={t("memo.importance")}
                    value={String(editor.importance)}
                    onChange={(value) =>
                      setEditor({
                        ...editor,
                        importance: Number(value) as ContextFactImportancePreset,
                        importanceDirty: true,
                      })
                    }
                    options={importanceOptions}
                    className="memo-context-editor__importance-select"
                  />
                </div>
                <label className="memo-context-editor__field" htmlFor="context-fact-title">
                  <span className="memo-context-editor__label">{t("memo.titleLabel")}</span>
                  <input
                    ref={titleInputRef}
                    id="context-fact-title"
                    className="memo-context-editor__title"
                    type="text"
                    maxLength={100}
                    required
                    placeholder={t("memo.contextTitlePlaceholder")}
                    value={editor.title}
                    onChange={(e) => setEditor({ ...editor, title: e.target.value })}
                  />
                </label>
                <label className="memo-context-editor__field" htmlFor="context-fact-content">
                  <span className="memo-context-editor__label">{t("memo.content")}</span>
                  <textarea
                    id="context-fact-content"
                    className="memo-context-editor__content"
                    maxLength={2000}
                    rows={4}
                    required
                    placeholder={t("memo.contextContentPlaceholder")}
                    value={editor.content}
                    onChange={(e) => setEditor({ ...editor, content: e.target.value })}
                  />
                </label>
              </div>
              <footer className="cc-modal__footer">
                <button
                  type="button"
                  className="cc-modal__btn"
                  onClick={closeEditor}
                  disabled={submitting}
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  className="cc-modal__btn cc-modal__btn--primary"
                  disabled={submitting}
                >
                  {submitting ? t("common.saving") : editor.mode === "create" ? t("memo.add") : t("memo.update")}
                </button>
              </footer>
            </form>
          </div>
        </ModalShell>
      )}

      {isLoading ? (
        <MemoListSkeleton />
      ) : error ? (
        <div className="memo-context-empty" role="alert">
          <p className="memo-context-empty__text">
            {error instanceof Error ? error.message : t("memo.loadContextFailed")}
          </p>
        </div>
      ) : facts.length === 0 ? (
        <div className="memo-context-empty">
          <i className="bi bi-safe" aria-hidden="true"></i>
          <p className="memo-context-empty__text">
            {statusFilter === "active"
              ? t("memo.noContext")
              : t("memo.noDeprecatedContext")}
          </p>
        </div>
      ) : (
        <>
          <ul className="memo-context-list">
            {facts.map((fact) => (
              <li key={fact.id}>
                <article
                  className={`memo-context-card${fact.status === "deprecated" ? " is-deprecated" : ""}`}
                >
                  <div className="memo-context-card__head">
                    <span
                      className={`memo-context-card__badge memo-context-card__badge--${fact.fact_type}`}
                    >
                      {t(factTypeKeys[fact.fact_type])}
                    </span>
                    <h3 className="memo-context-card__title">{fact.title}</h3>
                  </div>
                  <MemoMarkdown
                    className="memo-context-card__body md-content"
                    text={fact.content}
                  />
                  <div className="memo-context-card__meta">
                    <span>{t("memo.source", { source: sourceLabel(fact.source_kind) })}</span>
                    <span>{t("memo.importanceValue", { value: importanceLabel(fact.importance) })}</span>
                  </div>
                  <div className="memo-context-card__actions">
                    <button
                      type="button"
                      className="memo-context-card__action"
                      onClick={() => openEdit(fact)}
                      disabled={busyFactId === fact.id}
                    >
                      <i className="bi bi-pencil" aria-hidden="true"></i>
                      <span>{t("common.edit")}</span>
                    </button>
                    <button
                      type="button"
                      className="memo-context-card__action"
                      onClick={() => handleToggleStatus(fact)}
                      disabled={busyFactId === fact.id}
                    >
                      <i
                        className={`bi ${fact.status === "active" ? "bi-archive" : "bi-arrow-counterclockwise"}`}
                        aria-hidden="true"
                      ></i>
                      <span>{fact.status === "active" ? t("memo.deactivate") : t("memo.restore")}</span>
                    </button>
                  </div>
                </article>
              </li>
            ))}
          </ul>
          {nextCursor && (
            <div className="memo-context__pagination">
              <button
                type="button"
                className="memo-context__load-more"
                onClick={() => void handleLoadMore()}
                disabled={loadingMore}
              >
                {loadingMore ? t("common.loading") : t("memo.loadMore")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
