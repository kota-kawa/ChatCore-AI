import { useMemo, useState } from "react";
import useSWR from "swr";

import {
  createContextFact as defaultCreate,
  loadContextFacts as defaultLoad,
  updateContextFact as defaultUpdate,
} from "../../lib/memo/context_api";
import {
  CONTEXT_FACT_TYPE_LABELS,
  CONTEXT_FACT_TYPE_OPTIONS,
  type ContextFact,
  type ContextFactStatus,
  type ContextFactType,
} from "../../lib/memo/context_types";
import { MemoListSkeleton } from "./MemoListSkeleton";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";

type ContextApi = {
  load: typeof defaultLoad;
  create: typeof defaultCreate;
  update: typeof defaultUpdate;
};

type MyContextPanelProps = {
  isLoggedIn: boolean;
  api?: Partial<ContextApi>;
};

type EditorState = {
  mode: "create" | "edit";
  factId: number | null;
  revision: number;
  factType: ContextFactType;
  title: string;
  content: string;
};

const EMPTY_EDITOR: EditorState = {
  mode: "create",
  factId: null,
  revision: 0,
  factType: "preference",
  title: "",
  content: "",
};

export function MyContextPanel({ isLoggedIn, api }: MyContextPanelProps) {
  const load = api?.load ?? defaultLoad;
  const create = api?.create ?? defaultCreate;
  const update = api?.update ?? defaultUpdate;

  const [statusFilter, setStatusFilter] = useState<ContextFactStatus>("active");
  const [typeFilter, setTypeFilter] = useState<ContextFactType | "all">("all");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [busyFactId, setBusyFactId] = useState<number | null>(null);

  const swrKey = isLoggedIn ? `context-facts|${statusFilter}|${typeFilter}` : null;
  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () =>
      load({
        factType: typeFilter === "all" ? null : typeFilter,
        status: statusFilter,
      }),
    { revalidateOnFocus: false },
  );

  const facts = data?.facts ?? [];
  const totalActive = data?.totalActive ?? 0;

  const typeOptions = useMemo(
    () => [{ value: "all", label: "すべての種類" }, ...CONTEXT_FACT_TYPE_OPTIONS],
    [],
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
      title: fact.title,
      content: fact.content,
    });
  };

  const closeEditor = () => {
    setEditor(null);
    setSubmitting(false);
  };

  const handleSubmit = async () => {
    if (!editor) return;
    if (!editor.title.trim() || !editor.content.trim()) {
      setErrorText("タイトルと内容を入力してください。");
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
        });
      } else if (editor.factId !== null) {
        await update(editor.factId, {
          revision: editor.revision,
          fact_type: editor.factType,
          title: editor.title.trim(),
          content: editor.content.trim(),
        });
      }
      closeEditor();
      await mutate();
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : "保存に失敗しました。");
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
      setErrorText(err instanceof Error ? err.message : "状態の変更に失敗しました。");
    } finally {
      setBusyFactId(null);
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="memo-context memo-context--guest">
        <div className="memo-context-empty">
          <i className="bi bi-safe" aria-hidden="true"></i>
          <h2 className="memo-context-empty__title">マイコンテキスト</h2>
          <p className="memo-context-empty__text">
            あなたの好み・経歴・プロジェクト文脈・過去の決定を一元保存し、MCP連携で
            Claude・ChatGPT・Cursor などどのAIにも記憶を引き継げます。ログインすると利用できます。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="memo-context">
      <header className="memo-context__header">
        <div className="memo-context__heading">
          <h1 className="memo-context__title">マイコンテキスト</h1>
          <p className="memo-context__subtitle">
            保存した事実は、接続したAIサービスにMCP経由で共有できます（有効: {totalActive} 件）。
          </p>
        </div>
        <button type="button" className="memo-context__add-btn" onClick={openCreate}>
          <i className="bi bi-plus-lg" aria-hidden="true"></i>
          <span>コンテキストを追加</span>
        </button>
      </header>

      <div className="memo-context__filters">
        <MemoSelect
          value={typeFilter}
          onChange={(v) => setTypeFilter(v as ContextFactType | "all")}
          options={typeOptions}
          className="memo-context__filter-select"
        />
        <div className="memo-context__status-toggle" role="group" aria-label="状態フィルタ">
          <button
            type="button"
            className={`memo-context__status-btn${statusFilter === "active" ? " is-active" : ""}`}
            onClick={() => setStatusFilter("active")}
          >
            有効
          </button>
          <button
            type="button"
            className={`memo-context__status-btn${statusFilter === "deprecated" ? " is-active" : ""}`}
            onClick={() => setStatusFilter("deprecated")}
          >
            無効化済み
          </button>
        </div>
      </div>

      {errorText && (
        <div className="memo-flash memo-flash--error" role="alert">
          {errorText}
        </div>
      )}

      {editor && (
        <section className="memo-context-editor" aria-label="コンテキスト編集">
          <div className="memo-context-editor__row">
            <label className="memo-context-editor__label" htmlFor="context-fact-type">
              種類
            </label>
            <MemoSelect
              id="context-fact-type"
              value={editor.factType}
              onChange={(v) => setEditor({ ...editor, factType: v as ContextFactType })}
              options={CONTEXT_FACT_TYPE_OPTIONS}
              className="memo-context-editor__select"
            />
          </div>
          <input
            className="memo-context-editor__title"
            type="text"
            maxLength={100}
            placeholder="タイトル（例: エディタの好み）"
            value={editor.title}
            onChange={(e) => setEditor({ ...editor, title: e.target.value })}
          />
          <textarea
            className="memo-context-editor__content"
            maxLength={2000}
            rows={4}
            placeholder="内容（Markdown可、2000文字まで）"
            value={editor.content}
            onChange={(e) => setEditor({ ...editor, content: e.target.value })}
          />
          <div className="memo-context-editor__actions">
            <button
              type="button"
              className="memo-context-editor__cancel"
              onClick={closeEditor}
              disabled={submitting}
            >
              キャンセル
            </button>
            <button
              type="button"
              className="memo-context-editor__save"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? "保存中…" : editor.mode === "create" ? "追加" : "更新"}
            </button>
          </div>
        </section>
      )}

      {isLoading ? (
        <MemoListSkeleton />
      ) : error ? (
        <div className="memo-context-empty">
          <p className="memo-context-empty__text">コンテキストを取得できませんでした。</p>
        </div>
      ) : facts.length === 0 ? (
        <div className="memo-context-empty">
          <i className="bi bi-safe" aria-hidden="true"></i>
          <p className="memo-context-empty__text">
            {statusFilter === "active"
              ? "まだコンテキストがありません。「コンテキストを追加」から保存してみましょう。"
              : "無効化済みのコンテキストはありません。"}
          </p>
        </div>
      ) : (
        <ul className="memo-context-list">
          {facts.map((fact) => (
            <li key={fact.id}>
              <article
                className={`memo-context-card${fact.status === "deprecated" ? " is-deprecated" : ""}`}
              >
                <div className="memo-context-card__head">
                  <span className={`memo-context-card__badge memo-context-card__badge--${fact.fact_type}`}>
                    {CONTEXT_FACT_TYPE_LABELS[fact.fact_type]}
                  </span>
                  <h3 className="memo-context-card__title">{fact.title}</h3>
                </div>
                <MemoMarkdown className="memo-context-card__body md-content" text={fact.content} />
                <div className="memo-context-card__actions">
                  <button
                    type="button"
                    className="memo-context-card__action"
                    onClick={() => openEdit(fact)}
                    disabled={busyFactId === fact.id}
                  >
                    <i className="bi bi-pencil" aria-hidden="true"></i>
                    <span>編集</span>
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
                    <span>{fact.status === "active" ? "無効化" : "復元"}</span>
                  </button>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
