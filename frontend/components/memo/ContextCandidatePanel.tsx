import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import { useModalFocusTrap } from "../../hooks/use_modal_focus_trap";
import {
  approveContextCandidate as defaultApprove,
  loadContextCandidates as defaultLoad,
  loadContextExtractionSettings as defaultLoadSettings,
  rejectContextCandidate as defaultReject,
  updateContextExtractionSettings as defaultUpdateSettings,
} from "../../lib/memo/context_api";
import {
  CONTEXT_FACT_TYPE_OPTIONS,
  type ContextFactCandidate,
  type ContextFactType,
} from "../../lib/memo/context_types";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";

export type ContextCandidateApi = {
  load: typeof defaultLoad;
  approve: typeof defaultApprove;
  reject: typeof defaultReject;
  loadSettings: typeof defaultLoadSettings;
  updateSettings: typeof defaultUpdateSettings;
};

type ContextCandidatePanelProps = {
  api?: Partial<ContextCandidateApi>;
  onApproved?: () => void | Promise<unknown>;
};

type ApprovalReview = {
  kind: "approve";
  candidate: ContextFactCandidate;
  factType: ContextFactType;
  title: string;
  content: string;
  importance: number;
};

type RejectionReview = {
  kind: "reject";
  candidate: ContextFactCandidate;
};

type ReviewState = ApprovalReview | RejectionReview;

const CANDIDATE_PAGE_LIMIT = 20;

function confidenceLabel(confidence: number): string {
  const normalized = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.max(0, Math.min(100, Math.round(normalized)))}%`;
}

export function ContextCandidatePanel({ api, onApproved }: ContextCandidatePanelProps) {
  const { t } = useTranslation();
  const factTypeKeys: Record<ContextFactType, MessageKey> = {
    profile: "memo.factTypeProfile", preference: "memo.factTypePreference", project: "memo.factTypeProject",
    decision: "memo.factTypeDecision", reference: "memo.factTypeReference",
  };
  const factTypeOptions = CONTEXT_FACT_TYPE_OPTIONS.map((option) => ({ ...option, label: t(factTypeKeys[option.value as ContextFactType]) }));
  const sourceLabel = (source: string) => source === "manual" ? t("memo.sourceManual") : source === "chat" ? t("memo.sourceChat") : source === "import" ? t("memo.sourceImport") : source;
  const load = api?.load ?? defaultLoad;
  const approve = api?.approve ?? defaultApprove;
  const reject = api?.reject ?? defaultReject;
  const loadSettings = api?.loadSettings ?? defaultLoadSettings;
  const updateSettings = api?.updateSettings ?? defaultUpdateSettings;

  const { data, error, isLoading, mutate } = useSWR(
    "context-candidates|pending",
    () => load({ status: "pending", limit: CANDIDATE_PAGE_LIMIT }),
    { revalidateOnFocus: false },
  );
  const {
    data: settings,
    error: settingsError,
    isLoading: settingsLoading,
    mutate: mutateSettings,
  } = useSWR("context-extraction-settings", loadSettings, { revalidateOnFocus: false });

  const [additionalCandidates, setAdditionalCandidates] = useState<ContextFactCandidate[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busyCandidateId, setBusyCandidateId] = useState<number | null>(null);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewState | null>(null);
  const activeCursorRef = useRef<string | null>(null);
  const listVersionRef = useRef(0);
  const modalRef = useRef<HTMLElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    listVersionRef.current += 1;
    setAdditionalCandidates([]);
    setNextCursor(data?.nextCursor ?? null);
    setLoadingMore(false);
    activeCursorRef.current = null;
  }, [data]);

  const candidates = useMemo(() => {
    const uniqueCandidates = new Map<number, ContextFactCandidate>();
    for (const candidate of [...(data?.candidates ?? []), ...additionalCandidates]) {
      if (!uniqueCandidates.has(candidate.id)) uniqueCandidates.set(candidate.id, candidate);
    }
    return [...uniqueCandidates.values()];
  }, [additionalCandidates, data?.candidates]);

  const closeReview = useCallback(() => {
    setReview(null);
    setErrorText(null);
  }, []);

  const closeReviewWithEscape = useCallback(() => {
    if (busyCandidateId === null) closeReview();
  }, [busyCandidateId, closeReview]);

  const getInitialModalFocus = useCallback(
    () => titleInputRef.current ?? confirmButtonRef.current ?? modalRef.current,
    [],
  );

  useModalFocusTrap({
    isOpen: review !== null,
    containerRef: modalRef,
    getInitialFocus: getInitialModalFocus,
    onEscape: closeReviewWithEscape,
  });
  useBodyScrollLock(review !== null);

  const refreshAfterApproval = async () => {
    const results = await Promise.allSettled([
      Promise.resolve().then(() => mutate()),
      Promise.resolve().then(() => onApproved?.()),
    ]);
    if (results.some((result) => result.status === "rejected")) {
      setErrorText(t("memo.approvedRefreshFailed"));
    }
  };

  const handleApprove = async (candidate: ContextFactCandidate) => {
    setBusyCandidateId(candidate.id);
    setErrorText(null);
    try {
      await approve(candidate.id, { revision: candidate.revision });
      await refreshAfterApproval();
    } catch (approvalError) {
      setErrorText(
        approvalError instanceof Error ? approvalError.message : t("memo.approveSuggestionFailed"),
      );
    } finally {
      setBusyCandidateId(null);
    }
  };

  const openApprovalReview = (candidate: ContextFactCandidate) => {
    setErrorText(null);
    setReview({
      kind: "approve",
      candidate,
      factType: candidate.fact_type,
      title: candidate.title,
      content: candidate.content,
      importance: candidate.importance,
    });
  };

  const submitApprovalReview = async () => {
    if (!review || review.kind !== "approve") return;
    const title = review.title.trim();
    const content = review.content.trim();
    if (!title || !content) {
      setErrorText(t("memo.titleContentRequired"));
      return;
    }
    if (!Number.isFinite(review.importance) || review.importance < 0 || review.importance > 100) {
      setErrorText(t("memo.importanceRange"));
      return;
    }

    const { candidate } = review;
    setBusyCandidateId(candidate.id);
    setErrorText(null);
    try {
      await approve(candidate.id, {
        revision: candidate.revision,
        fact_type: review.factType,
        title,
        content,
        importance: review.importance,
      });
      setReview(null);
      await refreshAfterApproval();
    } catch (approvalError) {
      setErrorText(
        approvalError instanceof Error ? approvalError.message : t("memo.approveSuggestionFailed"),
      );
    } finally {
      setBusyCandidateId(null);
    }
  };

  const submitRejection = async () => {
    if (!review || review.kind !== "reject") return;
    const { candidate } = review;
    setBusyCandidateId(candidate.id);
    setErrorText(null);
    try {
      await reject(candidate.id, { revision: candidate.revision });
      setReview(null);
    } catch (rejectionError) {
      setErrorText(
        rejectionError instanceof Error ? rejectionError.message : t("memo.rejectSuggestionFailed"),
      );
      setBusyCandidateId(null);
      return;
    }

    const refreshResult = await Promise.allSettled([mutate()]);
    if (refreshResult[0]?.status === "rejected") {
      setErrorText(t("memo.rejectedRefreshFailed"));
    }
    setBusyCandidateId(null);
  };

  const handleLoadMore = async () => {
    if (!nextCursor || loadingMore || busyCandidateId !== null || activeCursorRef.current) return;
    const requestedCursor = nextCursor;
    const requestedListVersion = listVersionRef.current;
    activeCursorRef.current = requestedCursor;
    setLoadingMore(true);
    setErrorText(null);
    try {
      const page = await load({
        status: "pending",
        limit: CANDIDATE_PAGE_LIMIT,
        cursor: requestedCursor,
      });
      if (listVersionRef.current !== requestedListVersion) return;
      const knownIds = new Set(candidates.map((candidate) => candidate.id));
      const newCandidates: ContextFactCandidate[] = [];
      for (const candidate of page.candidates) {
        if (knownIds.has(candidate.id)) continue;
        knownIds.add(candidate.id);
        newCandidates.push(candidate);
      }
      setAdditionalCandidates((current) => [...current, ...newCandidates]);
      setNextCursor(page.nextCursor === requestedCursor ? null : page.nextCursor);
    } catch (loadError) {
      setErrorText(
        loadError instanceof Error ? loadError.message : t("memo.loadMoreSuggestionsFailed"),
      );
    } finally {
      if (activeCursorRef.current === requestedCursor) {
        activeCursorRef.current = null;
        setLoadingMore(false);
      }
    }
  };

  const handleSettingsToggle = async () => {
    if (settingsBusy || settingsLoading) return;
    const nextEnabled = !(settings?.enabled ?? false);
    setSettingsBusy(true);
    setErrorText(null);
    try {
      const updated = await updateSettings({ enabled: nextEnabled });
      await mutateSettings(updated, { revalidate: false });
    } catch (settingsUpdateError) {
      setErrorText(
        settingsUpdateError instanceof Error
          ? settingsUpdateError.message
          : t("memo.updateExtractionFailed"),
      );
    } finally {
      setSettingsBusy(false);
    }
  };

  const totalPending = data?.totalPending ?? 0;
  const settingEnabled = settings?.enabled ?? false;

  return (
    <section className="memo-context-candidates" aria-labelledby="context-candidates-title">
      <header className="memo-context-candidates__header">
        <div>
          <div className="memo-context-candidates__title-row">
            <h2 id="context-candidates-title">{t("memo.aiSuggestions")}</h2>
            <span className="memo-context-candidates__count" aria-label={t("memo.pendingCount", { count: totalPending })}>
              {totalPending}
            </span>
          </div>
          <p>{t("memo.suggestionsDescription")}</p>
        </div>
      </header>

      <div className="memo-context-extraction-setting">
        <div className="memo-context-extraction-setting__copy">
          <strong>{t("memo.extractionSettingTitle")}</strong>
          <p>{t("memo.extractionSettingDescription")}</p>
        </div>
        <button
          type="button"
          className={`memo-context-extraction-setting__toggle${settingEnabled ? " is-enabled" : ""}`}
          role="switch"
          aria-checked={settingEnabled}
          aria-label={t("memo.autoExtraction")}
          onClick={() => void handleSettingsToggle()}
          disabled={settingsBusy || settingsLoading || Boolean(settingsError)}
        >
          <span aria-hidden="true" />
          <span className="sr-only">{settingEnabled ? t("memo.active") : t("memo.disabled")}</span>
        </button>
      </div>

      {((!review && errorText) || error || settingsError) && (
        <div className="memo-flash memo-flash--error" role="alert">
          {(!review ? errorText : null) ||
            (error instanceof Error ? error.message : null) ||
            (settingsError instanceof Error ? settingsError.message : null) ||
            t("memo.loadSuggestionsFailed")}
        </div>
      )}

      {isLoading ? (
        <p className="memo-context-candidates__state">{t("memo.loadingSuggestions")}</p>
      ) : error ? null : candidates.length === 0 ? (
        <p className="memo-context-candidates__state">{t("memo.noPendingSuggestions")}</p>
      ) : (
        <ul className="memo-context-candidate-list">
          {candidates.map((candidate) => {
            const isBusy = busyCandidateId === candidate.id;
            return (
              <li key={candidate.id}>
                <article className="memo-context-candidate-card">
                  <div className="memo-context-candidate-card__head">
                    <span className="memo-context-card__badge">
                      {t(factTypeKeys[candidate.fact_type])}
                    </span>
                    <span className="memo-context-candidate-card__confidence">
                      {t("memo.confidence", { value: confidenceLabel(candidate.confidence) })}
                    </span>
                  </div>
                  <h3>{candidate.title}</h3>
                  <MemoMarkdown
                    className="memo-context-candidate-card__body md-content"
                    text={candidate.content}
                  />
                  <div className="memo-context-candidate-card__meta">
                    {t("memo.source", { source: sourceLabel(candidate.source_kind) })}
                  </div>
                  <div className="memo-context-candidate-card__actions">
                    <button
                      type="button"
                      className="memo-context-candidate-card__approve"
                      onClick={() => void handleApprove(candidate)}
                      disabled={isBusy}
                    >
                      {isBusy ? t("memo.processing") : t("memo.approve")}
                    </button>
                    <button
                      type="button"
                      onClick={() => openApprovalReview(candidate)}
                      disabled={isBusy}
                    >
                      {t("memo.editAndApprove")}
                    </button>
                    <button
                      type="button"
                      className="memo-context-candidate-card__reject"
                      onClick={() => {
                        setErrorText(null);
                        setReview({ kind: "reject", candidate });
                      }}
                      disabled={isBusy}
                    >
                      {t("memo.reject")}
                    </button>
                  </div>
                </article>
              </li>
            );
          })}
        </ul>
      )}

      {nextCursor && (
        <button
          type="button"
          className="memo-context-candidates__load-more"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore || busyCandidateId !== null}
        >
          {loadingMore ? t("common.loading") : t("memo.loadMoreSuggestions")}
        </button>
      )}

      {review && typeof document !== "undefined" &&
        createPortal(
          <div className="memo-context-modal">
            <div
              className="memo-context-modal__overlay"
              aria-hidden="true"
              onClick={() => {
                if (busyCandidateId === null) closeReview();
              }}
            />
            <section
              ref={modalRef}
              className="memo-context-modal__content memo-context-candidate-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="context-candidate-modal-title"
              tabIndex={-1}
            >
              <header className="memo-context-modal__header">
                <div>
                  <h2 id="context-candidate-modal-title">
                    {review.kind === "approve" ? t("memo.editAndApproveTitle") : t("memo.rejectSuggestion")}
                  </h2>
                  <p>{review.candidate.title}</p>
                </div>
                <button
                  type="button"
                  className="memo-context-modal__close"
                  aria-label={t("common.close")}
                  onClick={closeReview}
                  disabled={busyCandidateId !== null}
                >
                  <i className="bi bi-x-lg" aria-hidden="true" />
                </button>
              </header>

              {errorText && (
                <div className="memo-flash memo-flash--error" role="alert">
                  {errorText}
                </div>
              )}

              {review.kind === "approve" ? (
                <form
                  className="memo-context-candidate-modal__form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submitApprovalReview();
                  }}
                >
                  <label>
                    <span>{t("memo.type")}</span>
                    <MemoSelect
                      ariaLabel={t("memo.candidateType")}
                      value={review.factType}
                      options={factTypeOptions}
                      onChange={(value) =>
                        setReview((current) =>
                          current?.kind === "approve"
                            ? { ...current, factType: value as ContextFactType }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label htmlFor="context-candidate-title">
                    <span>{t("memo.titleLabel")}</span>
                    <input
                      ref={titleInputRef}
                      id="context-candidate-title"
                      value={review.title}
                      maxLength={100}
                      required
                      onChange={(event) =>
                        setReview((current) =>
                          current?.kind === "approve"
                            ? { ...current, title: event.target.value }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label htmlFor="context-candidate-content">
                    <span>{t("memo.content")}</span>
                    <textarea
                      id="context-candidate-content"
                      value={review.content}
                      maxLength={2000}
                      rows={5}
                      required
                      onChange={(event) =>
                        setReview((current) =>
                          current?.kind === "approve"
                            ? { ...current, content: event.target.value }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label htmlFor="context-candidate-importance">
                    <span>{t("memo.importance")}</span>
                    <input
                      id="context-candidate-importance"
                      type="number"
                      min={0}
                      max={100}
                      required
                      value={review.importance}
                      onChange={(event) =>
                        setReview((current) =>
                          current?.kind === "approve"
                            ? { ...current, importance: Number(event.target.value) }
                            : current,
                        )
                      }
                    />
                  </label>
                  <div className="memo-context-candidate-modal__actions">
                    <button type="button" onClick={closeReview} disabled={busyCandidateId !== null}>
                      {t("common.cancel")}
                    </button>
                    <button
                      ref={confirmButtonRef}
                      type="submit"
                      className="is-primary"
                      disabled={busyCandidateId !== null}
                    >
                      {busyCandidateId !== null ? t("memo.approving") : t("memo.approveContent")}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="memo-context-candidate-modal__confirmation">
                  <p>{t("memo.rejectConfirmation")}</p>
                  <div className="memo-context-candidate-modal__actions">
                    <button type="button" onClick={closeReview} disabled={busyCandidateId !== null}>
                      {t("common.cancel")}
                    </button>
                    <button
                      ref={confirmButtonRef}
                      type="button"
                      className="is-danger"
                      onClick={() => void submitRejection()}
                      disabled={busyCandidateId !== null}
                    >
                      {busyCandidateId !== null ? t("memo.rejecting") : t("memo.rejectAction")}
                    </button>
                  </div>
                </div>
              )}
            </section>
          </div>,
          document.body,
        )}
    </section>
  );
}
