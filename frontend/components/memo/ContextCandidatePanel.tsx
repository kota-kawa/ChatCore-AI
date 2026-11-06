// チャットなどから AI が抽出した「マイコンテキスト」の候補を一覧し、承認（内容を編集して登録）または却下するパネル。MyContextPanel から使われる。
// Panel that lists AI-extracted "my context" candidates (from chat and similar) for approval, with optional edits, or rejection; used by MyContextPanel.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
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
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";

// 通信関数の束。テストでは差し替えられるよう、props で上書きできる形にしている。
// Bundle of API functions; overridable through props so tests can swap them.
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

// 確認モーダルの状態。承認は編集中の値を持ち、却下は対象の候補だけを持つ。
// State of the review modal: approval carries the values being edited, rejection only the target candidate.
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

// 候補を1回で取得する件数。続きは nextCursor で追加取得する。
// Candidates fetched per request; the rest is loaded through nextCursor.
const CANDIDATE_PAGE_LIMIT = 20;

// 信頼度を 0〜100% の表記にする。1 以下の値は 0〜1 の割合として扱う。
// Formats confidence as 0-100%; values up to 1 are treated as a 0-1 ratio.
function confidenceLabel(confidence: number): string {
  const normalized = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.max(0, Math.min(100, Math.round(normalized)))}%`;
}

// 承認待ちの候補一覧・自動抽出の ON/OFF 切り替え・承認/却下の確認モーダルをまとめるパネル。
// Panel combining the pending-candidate list, the auto-extraction toggle, and the approve/reject review modal.
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
  // 一覧の世代番号。再取得で一覧が入れ替わったあとに、古い「さらに読み込む」の結果を捨てるために使う。
  // Generation counter of the list; lets a stale "load more" result be dropped after the list was refreshed.
  const listVersionRef = useRef(0);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    // 先頭ページが更新されたら、追加読み込み分と進行中の読み込みを破棄して先頭からやり直す。
    // When the first page refreshes, discard the extra pages and any in-flight load and start over.
    listVersionRef.current += 1;
    setAdditionalCandidates([]);
    setNextCursor(data?.nextCursor ?? null);
    setLoadingMore(false);
    activeCursorRef.current = null;
  }, [data]);

  // 先頭ページと追加ページを結合し、id の重複を除く（再取得で境界が重なっても二重表示しない）。
  // Merge the first page and the extra pages, dropping duplicate ids so overlapping pages never show a row twice.
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

  const getInitialModalFocus = useCallback(
    () => titleInputRef.current ?? confirmButtonRef.current,
    [],
  );

  // フォーカストラップと Escape は ModalShell が担う。スクロールロックだけをここで持つ。
  // ModalShell owns the focus trap and Escape; only the scroll lock lives here.
  useBodyScrollLock(review !== null);

  // 承認後に一覧と親（マイコンテキスト）を更新する。片方が失敗してももう片方は実行し、失敗だけ通知する。
  // Refresh the list and the parent (my context) after approval; one failing does not skip the other, and only the failure is reported.
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
      // 取得時の revision を添えて送る。サーバー側で候補が更新済みなら承認は拒否される。
      // Send the revision seen at load time; the server rejects the approval if the candidate has changed since.
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

  // 次のページを読み込む。多重実行と、一覧が入れ替わったあとの古い結果の反映を防ぐ。
  // Loads the next page, guarding against concurrent runs and against applying a result that arrived after the list was replaced.
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

  // 自動抽出の設定を切り替え、返ってきた最新値で設定キャッシュを直接更新する（再取得はしない）。
  // Toggles auto-extraction and writes the returned value straight into the settings cache without revalidating.
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

  // 確認モーダルを開いている間の操作エラーはモーダル内に出すので、一覧側のバナーには出さない。
  // While the review modal is open, action errors show inside it, so the list banner leaves them out.
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

      <ModalShell
        isOpen={review !== null}
        onClose={closeReview}
        id="context-candidate-modal"
        className="cc-modal memo-modal-scope memo-context-modal memo-context-candidate-modal"
        labelledBy="context-candidate-modal-title"
        dismissDisabled={busyCandidateId !== null}
        getInitialFocus={getInitialModalFocus}
      >
        {review && (
          <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1}>
            <header className="cc-modal__header">
              <div className="cc-modal__heading">
                <h2 className="cc-modal__title" id="context-candidate-modal-title">
                  {review.kind === "approve" ? t("memo.editAndApproveTitle") : t("memo.rejectSuggestion")}
                </h2>
                <p className="cc-modal__lead">{review.candidate.title}</p>
              </div>
              <ModalCloseButton label={t("common.close")} onClick={closeReview} disabled={busyCandidateId !== null} />
            </header>
            {review.kind === "approve" ? (
              <form
                className="cc-modal__form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitApprovalReview();
                }}
              >
                <div className="cc-modal__body memo-context-candidate-modal__form">
                  {errorText && (
                    <div className="cc-modal__notice memo-context-modal__error" role="alert">
                      {errorText}
                    </div>
                  )}
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
                </div>
                <footer className="cc-modal__footer">
                  <button type="button" className="cc-modal__btn" onClick={closeReview} disabled={busyCandidateId !== null}>
                    {t("common.cancel")}
                  </button>
                  <button
                    ref={confirmButtonRef}
                    type="submit"
                    className="cc-modal__btn cc-modal__btn--primary"
                    disabled={busyCandidateId !== null}
                  >
                    {busyCandidateId !== null ? t("memo.approving") : t("memo.approveContent")}
                  </button>
                </footer>
              </form>
            ) : (
              <>
                <div className="cc-modal__body memo-context-candidate-modal__confirmation">
                  {errorText && (
                    <div className="cc-modal__notice memo-context-modal__error" role="alert">
                      {errorText}
                    </div>
                  )}
                  <p>{t("memo.rejectConfirmation")}</p>
                </div>
                <footer className="cc-modal__footer">
                  <button type="button" className="cc-modal__btn" onClick={closeReview} disabled={busyCandidateId !== null}>
                    {t("common.cancel")}
                  </button>
                  <button
                    ref={confirmButtonRef}
                    type="button"
                    className="cc-modal__btn cc-modal__btn--primary memo-context-modal__btn--danger"
                    onClick={() => void submitRejection()}
                    disabled={busyCandidateId !== null}
                  >
                    {busyCandidateId !== null ? t("memo.rejecting") : t("memo.rejectAction")}
                  </button>
                </footer>
              </>
            )}
          </div>
        )}
      </ModalShell>
    </section>
  );
}
