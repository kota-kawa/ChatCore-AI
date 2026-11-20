// 記憶の画面の一覧の 1 件。種類・タイトル・本文に加えて、出所、最後に話題に出た日、出典（開くと本人の発話の引用と、その会話へのリンク）、
// 置き換えの履歴（有効なら「以前の記憶」と「元に戻す」、無効化済みなら置き換えた新しい記憶）、編集・無効化／復元・完全に削除の操作を持つ。MyContextPanel から使われる。
// One memory on the memory screen's list: type, title and body, plus where it came from, when it was last mentioned, its sources (opened to show quotes of
// the owner's words and a link to that conversation), its replacement history (an active memory shows "previous memory" and "undo", a deprecated one the newer
// memory that replaced it), and the edit / deactivate-or-restore / delete-for-good actions. Used by MyContextPanel.
import Link from "next/link";
import { useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { buildHomeRoomUrl } from "../../lib/chat_page/room_url";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";
import type { ContextFact, ContextFactType } from "../../lib/memo/context_types";
import { MemoMarkdown } from "./MemoMarkdown";

// 種類ごとの表示名の翻訳キー。
// Translation keys for each fact type's display name.
export const CONTEXT_FACT_TYPE_MESSAGE_KEYS: Record<ContextFactType, MessageKey> = {
  profile: "memo.factTypeProfile",
  preference: "memo.factTypePreference",
  project: "memo.factTypeProject",
  decision: "memo.factTypeDecision",
  reference: "memo.factTypeReference",
};

const SOURCE_KIND_MESSAGE_KEYS: Record<string, MessageKey> = {
  manual: "memo.sourceManual",
  chat: "memo.sourceChat",
  import: "memo.sourceImport",
  mcp: "memo.sourceMcp",
};

type ContextFactCardProps = {
  fact: ContextFact;
  // この記憶への操作を実行中は、操作ボタンを押せなくする。
  // While an action on this memory is running, its buttons are disabled.
  busy: boolean;
  onEdit: (fact: ContextFact) => void;
  onToggleStatus: (fact: ContextFact) => void;
  onRevert: (fact: ContextFact) => void;
  onDelete: (fact: ContextFact) => void;
};

export function ContextFactCard({ fact, busy, onEdit, onToggleStatus, onRevert, onDelete }: ContextFactCardProps) {
  const { t, formatDate } = useTranslation();
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const sources = fact.sources ?? [];
  const sourceCount = fact.source_count ?? 0;
  const isDeprecated = fact.status === "deprecated";
  const sourcesId = `context-fact-sources-${fact.id}`;
  const importanceLabel =
    fact.importance <= 33 ? t("memo.importanceLow") : fact.importance >= 67 ? t("memo.importanceHigh") : t("memo.importanceStandard");
  const sourceKindKey = SOURCE_KIND_MESSAGE_KEYS[fact.source_kind];
  const mentionedAt = fact.last_mentioned_at ? formatDate(fact.last_mentioned_at, { dateStyle: "medium" }) : null;

  return (
    <article className={`memo-context-card${isDeprecated ? " is-deprecated" : ""}`}>
      <div className="memo-context-card__head">
        <span className={`memo-context-card__badge memo-context-card__badge--${fact.fact_type}`}>
          {t(CONTEXT_FACT_TYPE_MESSAGE_KEYS[fact.fact_type])}
        </span>
        <h3 className="memo-context-card__title">{fact.title}</h3>
      </div>
      <MemoMarkdown className="memo-context-card__body md-content" text={fact.content} />

      {isDeprecated && fact.deprecated_reason === "superseded" && (
        <p className="memo-context-card__note">
          <i className="bi bi-arrow-repeat" aria-hidden="true"></i>
          <span>
            {fact.superseded_by
              ? t("memo.supersededBy", { title: fact.superseded_by.title })
              : t("memo.supersededByDeleted")}
          </span>
        </p>
      )}
      {!isDeprecated && fact.replaces && (
        <div className="memo-context-card__replaced">
          <p className="memo-context-card__replaced-text">
            <span className="memo-context-card__replaced-label">{t("memo.previousMemory")}</span>
            {fact.replaces.content}
          </p>
          <button type="button" className="memo-context-card__action" onClick={() => onRevert(fact)} disabled={busy}>
            <i className="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
            <span>{t("memo.revertReplacement")}</span>
          </button>
        </div>
      )}

      <div className="memo-context-card__meta">
        <span>{t("memo.source", { source: sourceKindKey ? t(sourceKindKey) : fact.source_kind })}</span>
        <span>{t("memo.importanceValue", { value: importanceLabel })}</span>
        {isDeprecated && fact.deprecated_reason === "capacity" && <span>{t("memo.deprecatedAtCapacity")}</span>}
        {mentionedAt && <span>{t("memo.lastMentioned", { date: mentionedAt })}</span>}
      </div>

      {sourceCount > 0 && sources.length > 0 && (
        <div className="memo-context-card__sources">
          <button
            type="button"
            className="memo-context-card__sources-toggle"
            aria-expanded={sourcesOpen}
            aria-controls={sourcesId}
            onClick={() => setSourcesOpen((open) => !open)}
          >
            <i className={`bi ${sourcesOpen ? "bi-chevron-up" : "bi-chevron-down"}`} aria-hidden="true"></i>
            <span>{t("memo.sourcesToggle", { count: sourceCount })}</span>
          </button>
          {sourcesOpen && (
            <div id={sourcesId} className="memo-context-card__sources-body">
              <ul className="memo-context-sources">
                {sources.map((source, index) => (
                  <li key={`${source.chat_room_id}-${source.observed_at ?? index}-${index}`} className="memo-context-source">
                    {/* 引用は本人の発話の一節。HTML として解釈させず、素のテキストとして出す。 */}
                    {/* The quote is a passage of the owner's words; render it as plain text, never as HTML. */}
                    <blockquote className="memo-context-source__quote">{source.evidence}</blockquote>
                    <div className="memo-context-source__foot">
                      {source.observed_at && (
                        <time dateTime={source.observed_at}>{formatDate(source.observed_at, { dateStyle: "medium" })}</time>
                      )}
                      <Link href={buildHomeRoomUrl(source.chat_room_id)} className="memo-context-source__link">
                        {t("memo.openConversation")}
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
              {sourceCount > sources.length && (
                <p className="memo-context-card__sources-more">
                  {t("memo.sourcesNewest", { shown: sources.length, count: sourceCount })}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="memo-context-card__actions">
        <button type="button" className="memo-context-card__action" onClick={() => onEdit(fact)} disabled={busy}>
          <i className="bi bi-pencil" aria-hidden="true"></i>
          <span>{t("common.edit")}</span>
        </button>
        <button type="button" className="memo-context-card__action" onClick={() => onToggleStatus(fact)} disabled={busy}>
          <i className={`bi ${isDeprecated ? "bi-arrow-counterclockwise" : "bi-archive"}`} aria-hidden="true"></i>
          <span>{isDeprecated ? t("memo.restore") : t("memo.deactivate")}</span>
        </button>
        <button
          type="button"
          className="memo-context-card__action memo-context-card__action--delete"
          onClick={() => onDelete(fact)}
          disabled={busy}
        >
          <i className="bi bi-trash3" aria-hidden="true"></i>
          <span>{t("memo.deletePermanently")}</span>
        </button>
      </div>
    </article>
  );
}
