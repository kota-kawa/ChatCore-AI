// 「記憶」（AI が回答に使うユーザーの事実・好み・方針）の画面。一覧（検索・出典・置き換えの履歴）と、追加・編集・無効化・復元・置き換えを元に戻す・完全な削除・すべての削除・書き出し/取り込みを行う。
// チャットからの自動保存と回答への利用の設定も内包する。MemoPage から使われる。
// The "memory" screen (facts, preferences, and decisions the AI may use in answers): the list (search, sources, replacement history) and add, edit, deactivate, restore, undo a replacement,
// delete for good, delete all, and export/import, with the auto-save and use-in-answers settings embedded. Used by MemoPage.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import { useContextFactDeletion } from "../../hooks/memo_page/use_context_fact_deletion";
import { useDebouncedValue } from "../../hooks/use_debounced_value";
import {
  createContextFact as defaultCreate,
  deleteAllContextFacts as defaultDeleteAll,
  deleteContextFact as defaultDeleteOne,
  loadContextFacts as defaultLoad,
  normalizeContextSearchQuery,
  revertContextFactReplacement as defaultRevert,
  updateContextFact as defaultUpdate,
  type ContextFactListResult,
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
import type { HttpError } from "../../lib/memo/types";
import { ContextDeleteAllModal } from "./ContextDeleteAllModal";
import { CONTEXT_FACT_TYPE_MESSAGE_KEYS, ContextFactCard } from "./ContextFactCard";
import { ContextFactDeleteModal } from "./ContextFactDeleteModal";
import { MemoListSkeleton } from "./MemoListSkeleton";
import { MemoSelect } from "./MemoSelect";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import {
  ContextExtractionSetting,
  type ContextExtractionApi,
} from "./ContextExtractionSetting";
import {
  ContextMemoryUseSetting,
  type ContextMemoryUseApi,
} from "./ContextMemoryUseSetting";
import {
  ContextPortabilityModal,
  type ContextPortabilityApi,
} from "./ContextPortabilityModal";
import { useTranslation } from "../../contexts/locale_context";

// 検索語の入力から取得までの待ち時間。打鍵のたびに取得せず、入力が止まってから 1 回だけ取る。
// How long to wait after the last keystroke before fetching, so typing causes one fetch instead of one per key.
const SEARCH_DEBOUNCE_MS = 300;
// 検索語の最大文字数。サーバーの MAX_CONTEXT_SEARCH_QUERY_LENGTH（blueprints/context_vault/constants.py）と揃える。
// The longest search query; keep in step with the server's MAX_CONTEXT_SEARCH_QUERY_LENGTH (blueprints/context_vault/constants.py).
const MAX_SEARCH_LENGTH = 200;

// 通信関数の束。テストでは props で差し替えられる。
// Bundle of API functions, overridable through props in tests.
// 取得結果。どの取得キーで取ったかを添える。
// A fetched page, carrying the fetch key it was fetched with.
type ContextFactsPage = ContextFactListResult & { requestKey: string };

// 「さらに読み込む」で足した分。base は、それが続きになっている先頭ページ。
// What "load more" added; base is the first page it continues.
type LoadedMore = { base: ContextFactsPage; facts: ContextFact[]; nextCursor: string | null };

const NO_FACTS: ContextFact[] = [];

type ContextApi = {
  load: typeof defaultLoad;
  create: typeof defaultCreate;
  update: typeof defaultUpdate;
  revert: typeof defaultRevert;
  deleteOne: typeof defaultDeleteOne;
  deleteAll: typeof defaultDeleteAll;
};

type MyContextPanelProps = {
  isLoggedIn: boolean;
  api?: Partial<ContextApi>;
  extractionApi?: Partial<ContextExtractionApi>;
  memoryUseApi?: Partial<ContextMemoryUseApi>;
  portabilityApi?: Partial<ContextPortabilityApi>;
};

// 追加・編集モーダルの入力状態。importanceDirty は、編集時に重要度を触ったときだけ送るための印。
// Input state of the add/edit modal; importanceDirty marks that importance was touched, so edits send it only then.
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

// 事実の一覧（状態・種類で絞り込み、カーソルで続きを読み込む）と、追加・編集モーダル、自動保存と回答への利用の設定を束ねる。
// Combines the fact list (filtered by status and type, with cursor-based "load more"), the add/edit modal, and the auto-save and use-in-answers settings.
export function MyContextPanel({
  isLoggedIn,
  api,
  extractionApi,
  memoryUseApi,
  portabilityApi,
}: MyContextPanelProps) {
  const { t } = useTranslation();
  const localizedTypeOptions = CONTEXT_FACT_TYPE_OPTIONS.map((option) => ({ ...option, label: t(CONTEXT_FACT_TYPE_MESSAGE_KEYS[option.value as ContextFactType]) }));
  const importanceOptions = CONTEXT_FACT_IMPORTANCE_OPTIONS.map((option) => ({ ...option, label: option.value === "25" ? t("memo.importanceLow") : option.value === "75" ? t("memo.importanceHigh") : t("memo.importanceStandard") }));
  const load = api?.load ?? defaultLoad;
  const create = api?.create ?? defaultCreate;
  const update = api?.update ?? defaultUpdate;
  const revert = api?.revert ?? defaultRevert;
  const deleteOne = api?.deleteOne ?? defaultDeleteOne;
  const deleteAll = api?.deleteAll ?? defaultDeleteAll;

  const [statusFilter, setStatusFilter] = useState<ContextFactStatus>("active");
  const [typeFilter, setTypeFilter] = useState<ContextFactType | "all">("all");
  const [searchInput, setSearchInput] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [busyFactId, setBusyFactId] = useState<number | null>(null);
  const [isPortabilityOpen, setIsPortabilityOpen] = useState(false);
  const [noticeText, setNoticeText] = useState<string | null>(null);
  const activeLoadMoreRef = useRef<ContextFactsPage | null>(null);
  const activeFilterKeyRef = useRef<string | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);

  // 検索は語の一致だけ（意味検索は使わない）。サーバーが使う形にそろえた語（句読点だけなら検索なし）を、入力が止まってから取得に使う。
  // Search is term matching only (no semantic search); the query, normalized to what the server uses (punctuation only means no search), is used for fetching once typing pauses.
  const searchQuery = useDebouncedValue(normalizeContextSearchQuery(searchInput), SEARCH_DEBOUNCE_MS);

  // 絞り込み条件ごとの取得キー。未ログインのときは null にして取得しない。キーの前半は状態・種類、最後が検索語。
  // Fetch key per filter combination; null when logged out so nothing is fetched. The prefix is status and type; the search query comes last.
  const filterKeyPrefix = `context-facts|${statusFilter}|${typeFilter}|`;
  const swrKey = isLoggedIn ? `${filterKeyPrefix}${searchQuery}` : null;
  activeFilterKeyRef.current = swrKey;
  // 取得結果には、どのキーで取ったかを添える。検索語だけが変わったときに前の結果を残してよいか、続きのカーソルがいまの条件のものかを見分けるため。
  // The result carries the key it was fetched with, to tell whether the previous result may stay while only the search query changes and whether its cursor belongs to the current filters.
  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    async () => ({
      ...(await load({
        factType: typeFilter === "all" ? null : typeFilter,
        status: statusFilter,
        ...(searchQuery ? { query: searchQuery } : {}),
      })),
      requestKey: `${filterKeyPrefix}${searchQuery}`,
    }),
    { revalidateOnFocus: false, keepPreviousData: true },
  );
  // 検索語が変わって取り直している間は、状態・種類が同じ前の結果をそのまま見せる（スケルトンに差し替えない）。状態・種類が変わったとき、
  // 前の結果が空だったときは、別の内容を見せないよう従来どおりスケルトンにする。
  // While refetching after a search-query change, the previous result with the same status and type stays on screen (no skeleton swap). When the
  // status or type changed, or the previous result was empty, the skeleton is shown so that no other content is displayed.
  const keepsPreviousResult = data !== undefined && data.facts.length > 0 && data.requestKey.startsWith(filterKeyPrefix);

  // 「さらに読み込む」の状態は、どの先頭ページ（data）に続くものかを添えて持ち、描画のたびにいまのキーの先頭ページと一致するものだけを使う。
  // キーが変わった直後や取り直した直後に、前の結果の続きのカーソル・追加分・読み込み中の印が一瞬でも残らない（effect で合わせる形にしない）。
  // The "load more" state carries the first page (data) it continues, and each render uses only what matches the first page of the current key, so a
  // cursor, extra facts or loading flag of a previous result never lingers for a render after the key changed or the list was refetched (no effect sync).
  const currentPage = data !== undefined && data.requestKey === swrKey ? data : null;
  const [loadedMore, setLoadedMore] = useState<LoadedMore | null>(null);
  const [loadingMoreOf, setLoadingMoreOf] = useState<ContextFactsPage | null>(null);
  const extra = loadedMore !== null && loadedMore.base === currentPage ? loadedMore : null;
  const additionalFacts = extra?.facts ?? NO_FACTS;
  const nextCursor = extra ? extra.nextCursor : (currentPage?.nextCursor ?? null);
  const loadingMore = loadingMoreOf !== null && loadingMoreOf === currentPage;

  // 削除の確認モーダルと実行。成功したら通知を出して一覧を取り直す。
  // The delete confirmation modals and their execution; on success the notice is shown and the list is reloaded.
  const deletion = useContextFactDeletion({
    deleteOne,
    deleteAll,
    onDeleted: async (message) => {
      setNoticeText(message);
      setLoadedMore(null);
      await mutate();
    },
  });

  useEffect(() => {
    setErrorText(null);
    setNoticeText(null);
  }, [swrKey]);

  // 先頭ページと追加ページを結合し、id の重複を除く。
  // Merge the first page and the extra pages, dropping duplicate ids.
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

  // 追加または編集を保存する。編集では取得時の revision を添え、重要度は変更したときだけ送る。
  // Saves an add or an edit; an edit sends the revision seen at load time and sends importance only if it was changed.
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

  // 事実の有効（active）と無効（deprecated）を切り替える。
  // Toggles a fact between active and deprecated.
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

  // 置き換えで入った新しい記憶を無効化し（この内容は再び覚えない）、置き換えられた古い記憶を有効へ戻す。
  // Deactivates the memory that came in by replacement (that content is not remembered again) and makes the older memory it replaced active again.
  const handleRevert = async (fact: ContextFact) => {
    setBusyFactId(fact.id);
    setErrorText(null);
    setNoticeText(null);
    try {
      await revert(fact.id, fact.revision);
      setNoticeText(t("memo.revertDone"));
      await mutate();
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : t("memo.revertFailed"));
      // 409 は置き換えが別の場所で先に変わった印。表示が古いままだと同じ操作が同じ理由で失敗し続けるので、一覧を取り直す。
      // A 409 means the replacement changed elsewhere first; a stale list would keep failing the same way, so reload it.
      if ((err as HttpError).status === 409) await mutate();
    } finally {
      setBusyFactId(null);
    }
  };

  // 次のページを読み込む。多重実行を避け、絞り込み条件が変わった後に届いた古い結果は反映しない。
  // Loads the next page, avoiding concurrent runs and ignoring a result that arrives after the filter changed.
  const handleLoadMore = async () => {
    if (!currentPage || !nextCursor || loadingMore || activeLoadMoreRef.current === currentPage) return;

    const requestedCursor = nextCursor;
    const requestedFilterKey = swrKey;
    const requestedPage = currentPage;
    activeLoadMoreRef.current = requestedPage;
    setLoadingMoreOf(requestedPage);
    setErrorText(null);
    try {
      const page = await load({
        factType: typeFilter === "all" ? null : typeFilter,
        status: statusFilter,
        cursor: requestedCursor,
        ...(searchQuery ? { query: searchQuery } : {}),
      });
      if (activeFilterKeyRef.current !== requestedFilterKey) return;

      const knownIds = new Set(facts.map((fact) => fact.id));
      const newFacts: ContextFact[] = [];
      for (const fact of page.facts) {
        if (knownIds.has(fact.id)) continue;
        knownIds.add(fact.id);
        newFacts.push(fact);
      }
      setLoadedMore((current) => ({
        base: requestedPage,
        facts: [...(current?.base === requestedPage ? current.facts : NO_FACTS), ...newFacts],
        nextCursor: page.nextCursor === requestedCursor ? null : page.nextCursor,
      }));
    } catch (err) {
      if (activeFilterKeyRef.current === requestedFilterKey) {
        setErrorText(err instanceof Error ? err.message : t("memo.loadMoreContextFailed"));
      }
    } finally {
      setLoadingMoreOf((current) => (current === requestedPage ? null : current));
      if (activeLoadMoreRef.current === requestedPage) activeLoadMoreRef.current = null;
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
          setLoadedMore(null);
          await mutate();
        }}
        api={portabilityApi}
      />

      <div className="memo-context-settings">
        <ContextExtractionSetting api={extractionApi} />
        <ContextMemoryUseSetting api={memoryUseApi} />
      </div>

      <div className="memo-context__filters">
        <div className="memo-context__search">
          <i className="bi bi-search" aria-hidden="true"></i>
          <input
            id="context-search"
            type="search"
            value={searchInput}
            maxLength={MAX_SEARCH_LENGTH}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t("memo.contextSearch")}
            aria-label={t("memo.contextSearch")}
          />
          {searchInput && (
            <button
              type="button"
              className="memo-context__search-clear"
              onClick={() => setSearchInput("")}
              aria-label={t("memo.contextSearchClear")}
            >
              <i className="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          )}
        </div>
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
      {noticeText && (
        <div className="memo-context__notice" role="status">
          <i className="bi bi-check-circle" aria-hidden="true"></i>
          <span>{noticeText}</span>
        </div>
      )}

      <ModalShell
        isOpen={editor !== null}
        onClose={closeEditor}
        id="context-editor-modal"
        className="cc-modal memo-modal-scope memo-context-modal memo-context-editor"
        labelledBy="context-editor-title"
        dismissDisabled={submitting}
        getInitialFocus={getInitialModalFocus}
      >
        {editor && (
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
        )}
      </ModalShell>

      {isLoading && !keepsPreviousResult ? (
        <MemoListSkeleton />
      ) : error ? (
        <div className="memo-context-empty" role="alert">
          <p className="memo-context-empty__text">
            {error instanceof Error ? error.message : t("memo.loadContextFailed")}
          </p>
        </div>
      ) : facts.length === 0 ? (
        <div className="memo-context-empty">
          <i className={`bi ${searchQuery ? "bi-search" : "bi-safe"}`} aria-hidden="true"></i>
          <p className="memo-context-empty__text">
            {searchQuery
              ? t("memo.noSearchResults", { query: searchQuery })
              : statusFilter === "active"
                ? t("memo.noContext")
                : t("memo.noDeprecatedContext")}
          </p>
        </div>
      ) : (
        <>
          <ul className="memo-context-list">
            {facts.map((fact) => (
              <li key={fact.id}>
                <ContextFactCard
                  fact={fact}
                  busy={busyFactId === fact.id}
                  onEdit={openEdit}
                  onToggleStatus={handleToggleStatus}
                  onRevert={handleRevert}
                  onDelete={deletion.openDelete}
                />
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

      <section className="memo-context__delete-all" aria-labelledby="context-delete-all-heading">
        <div className="memo-context__delete-all-copy">
          <h2 id="context-delete-all-heading" className="memo-context__delete-all-title">{t("memo.deleteAllHeading")}</h2>
          <p>{t("memo.deleteAllSectionDescription")}</p>
        </div>
        <button type="button" className="memo-context__delete-all-btn" onClick={deletion.openDeleteAll}>
          <i className="bi bi-trash3" aria-hidden="true"></i>
          <span>{t("memo.deleteAllOpen")}</span>
        </button>
      </section>

      <ContextFactDeleteModal
        fact={deletion.target}
        busy={deletion.deleting}
        errorText={deletion.errorText}
        onConfirm={() => void deletion.confirmDelete()}
        onClose={deletion.closeDelete}
      />
      <ContextDeleteAllModal
        isOpen={deletion.isAllOpen}
        activeCount={totalActive}
        busy={deletion.deletingAll}
        errorText={deletion.allErrorText}
        onConfirm={() => void deletion.confirmDeleteAll()}
        onClose={deletion.closeDeleteAll}
      />
    </div>
  );
}
