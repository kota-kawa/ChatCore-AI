import Link from "next/link";
import { memo, useCallback, useEffect, useId, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";
import type { ToolApprovalDecision } from "../../lib/chat_page/tool_approval_api";
import { isToolApprovalDecidable, isToolApprovalExpired } from "../../lib/chat_page/tool_approvals";
import type { ToolApprovalApi } from "../../types/generated/api_schemas";
import { MemoApprovalPreview } from "./tool_approval_previews/memo";

type Tool = ToolApprovalApi["tool"];
type Status = ToolApprovalApi["status"];
type Warning = NonNullable<ToolApprovalApi["warnings"]>[number];

const TITLE_KEYS: Record<Tool, MessageKey> = {
  memo_create: "chat.toolApproval.title.memo_create",
  memo_append: "chat.toolApproval.title.memo_append",
  memo_edit: "chat.toolApproval.title.memo_edit",
};

const TITLE_ICONS: Record<Tool, string> = {
  memo_create: "bi-journal-plus",
  memo_append: "bi-journal-arrow-down",
  memo_edit: "bi-pencil-square",
};

const WARNING_KEYS: Record<Warning, MessageKey> = {
  shared_memo: "chat.toolApproval.warning.shared_memo",
  untrusted_input_in_turn: "chat.toolApproval.warning.untrusted_input_in_turn",
  private_text_in_public_post: "chat.toolApproval.warning.private_text_in_public_post",
};

const STATUS_KEYS: Record<Status, MessageKey> = {
  pending: "chat.toolApproval.status.pending",
  succeeded: "chat.toolApproval.status.succeeded",
  failed: "chat.toolApproval.status.failed",
  denied: "chat.toolApproval.status.denied",
  expired: "chat.toolApproval.status.expired",
  superseded: "chat.toolApproval.status.superseded",
  cancelled: "chat.toolApproval.status.cancelled",
};

const STATUS_ICONS: Record<Status, string> = {
  pending: "bi-hourglass-split",
  succeeded: "bi-check-circle",
  failed: "bi-x-circle",
  denied: "bi-slash-circle",
  expired: "bi-hourglass-bottom",
  superseded: "bi-slash-circle",
  cancelled: "bi-slash-circle",
};

// 失敗理由のコードは言語非依存のデータとして届くので、表示文言はここで引く。知らないコードは汎用文にする。
// Failure reasons arrive as language-neutral codes, so the wording is looked up here; unknown codes fall
// back to a generic sentence.
const ERROR_KEYS = new Map<string, MessageKey>([
  ["target_not_found", "chat.toolApproval.error.target_not_found"],
  ["target_changed", "chat.toolApproval.error.target_changed"],
  ["target_shared", "chat.toolApproval.error.target_shared"],
  ["content_too_long", "chat.toolApproval.error.content_too_long"],
  ["invalid_content", "chat.toolApproval.error.invalid_content"],
]);

// setTimeout が扱える最大の待ち時間。これより先の期限は再描画で拾う。
// The longest delay setTimeout accepts; deadlines further out are caught on a later render.
const MAX_TIMER_DELAY_MS = 2_147_483_647;

// 期限の瞬間に再描画し、開いたままの画面でもボタンが押せなくなるようにする。
// Re-render at the deadline so the buttons lock even on a screen left open.
function useNowUntil(approval: ToolApprovalApi): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const expiresAtMs = approval.status === "pending" && approval.expires_at ? Date.parse(approval.expires_at) : NaN;

  useEffect(() => {
    if (!Number.isFinite(expiresAtMs)) return;
    const delay = expiresAtMs - Date.now();
    if (delay <= 0 || delay > MAX_TIMER_DELAY_MS) return;
    const timerId = window.setTimeout(() => setNowMs(Date.now()), delay + 50);
    return () => window.clearTimeout(timerId);
  }, [expiresAtMs]);

  return nowMs;
}

type Props = {
  approval: ToolApprovalApi;
  // 決定を送る。無いときは共有表示などの読み取り専用として描く
  // Sends the decision; without it the card renders read-only, as in a shared view
  onDecide?: (approvalId: string, decision: ToolApprovalDecision) => Promise<void>;
  // 生成中や、後ろに利用者の発言があるなど、今は決められない状態
  // The card cannot be decided right now: a reply is generating or the user already wrote after it
  disabled?: boolean;
};

// チャットの書き込みツールの承認カード。選択ボタンと同じ面とピルで、実行する内容のプレビューと
// 「1度だけ承認／常に承認／拒否」を出す。決まった後は状態と結果への導線だけを残す。
// Approval card for a chat write tool. It shares the choice buttons' panel and pills, showing a preview
// of what will run and "approve once / always approve / deny"; once decided, only the outcome and a
// link to the result remain.
function ToolApprovalCardComponent({ approval, onDecide, disabled = false }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const nowMs = useNowUntil(approval);
  // 押してから応答が届くまでの二重送信を防ぐ / Blocks a second send while the decision is in flight
  const [submitting, setSubmitting] = useState<ToolApprovalDecision | null>(null);

  const readOnly = !onDecide || approval.readonly;
  const expired = isToolApprovalExpired(approval, nowMs);
  const displayStatus: Status = expired ? "expired" : approval.status;
  const showActions = !readOnly && isToolApprovalDecidable(approval, nowMs);
  const inactive = disabled || submitting !== null;

  const decide = useCallback(
    async (decision: ToolApprovalDecision) => {
      if (inactive || !showActions || !onDecide) return;
      setSubmitting(decision);
      try {
        await onDecide(approval.id, decision);
      } finally {
        setSubmitting(null);
      }
    },
    [approval.id, inactive, onDecide, showActions],
  );

  const warnings = approval.warnings ?? [];
  const result = approval.result;
  const statusText =
    displayStatus === "succeeded" && approval.decision === "auto"
      ? t("chat.toolApproval.status.succeededAuto")
      : t(STATUS_KEYS[displayStatus]);
  const errorText =
    displayStatus === "failed"
      ? t(ERROR_KEYS.get(result?.error_code ?? "") ?? "chat.toolApproval.error.unknown")
      : "";
  const showResultLink = displayStatus === "succeeded" && typeof result?.target_id === "number";

  return (
    <div
      className="interactive-buttons-container tool-approval-card"
      data-status={displayStatus}
      role="group"
      aria-labelledby={titleId}
      aria-busy={submitting !== null}
    >
      <div className="interactive-buttons-header">
        <div id={titleId} className="interactive-buttons-question tool-approval-card__title">
          <i className={`bi ${TITLE_ICONS[approval.tool]}`} aria-hidden="true"></i>
          <span>{t(TITLE_KEYS[approval.tool])}</span>
        </div>
        {showActions ? <div className="interactive-buttons-hint">{t("chat.toolApproval.lead")}</div> : null}
      </div>

      {warnings.length > 0 ? (
        <ul className="tool-approval-card__warnings">
          {warnings.map((warning) => (
            <li key={warning} className="tool-approval-card__warning">
              <i className="bi bi-exclamation-triangle" aria-hidden="true"></i>
              <span>{t(WARNING_KEYS[warning])}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {approval.preview ? <MemoApprovalPreview preview={approval.preview} /> : null}

      {showActions ? (
        <>
          <div className="interactive-buttons-actions">
            <button
              type="button"
              className="interactive-button"
              disabled={inactive}
              onClick={() => void decide("approve_once")}
            >
              {approval.always_allowed ? t("chat.toolApproval.approveOnce") : t("chat.toolApproval.approve")}
            </button>
            {approval.always_allowed ? (
              <button
                type="button"
                className="interactive-button"
                disabled={inactive}
                onClick={() => void decide("approve_always")}
              >
                {t("chat.toolApproval.approveAlways")}
              </button>
            ) : null}
            <button
              type="button"
              className="interactive-button"
              disabled={inactive}
              onClick={() => void decide("deny")}
            >
              {t("chat.toolApproval.deny")}
            </button>
          </div>
          {submitting !== null ? (
            <div className="interactive-buttons-hint" role="status">{t("chat.toolApproval.deciding")}</div>
          ) : approval.always_allowed ? (
            <div className="interactive-buttons-hint">{t("chat.toolApproval.alwaysHint")}</div>
          ) : null}
        </>
      ) : (
        <div className="tool-approval-card__status" role="status">
          <i className={`bi ${STATUS_ICONS[displayStatus]}`} aria-hidden="true"></i>
          <div className="tool-approval-card__status-body">
            <div className="tool-approval-card__status-text">
              {statusText}
              {errorText ? <span className="tool-approval-card__status-detail">{errorText}</span> : null}
            </div>
            {showResultLink ? (
              <Link className="tool-approval-card__result-link" href="/memo">
                {result?.target_title ? <span className="tool-approval-card__result-title">{result.target_title}</span> : null}
                <span>{t("chat.toolApproval.openMemo")}</span>
                <i className="bi bi-arrow-right" aria-hidden="true"></i>
              </Link>
            ) : null}
          </div>
        </div>
      )}

      {readOnly && displayStatus === "pending" ? (
        <p className="interactive-buttons-readonly-note">{t("chat.toolApproval.readOnlyNote")}</p>
      ) : null}
    </div>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const ToolApprovalCard = memo(ToolApprovalCardComponent);
ToolApprovalCard.displayName = "ToolApprovalCard";
