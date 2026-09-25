import {
  ToolApprovalDecisionResponseSchema,
  type ToolApprovalApi,
  type ToolApprovalDecisionRequest,
} from "../../types/generated/api_schemas";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { extractApiErrorMessage, fetchJson, isRecord } from "../../scripts/core/runtime_validation";
import { normalizeToolApproval } from "./api_contract";

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type ToolApprovalDecision = ToolApprovalDecisionRequest["decision"];

// 承認 API の失敗。画面は code で分岐する（期限切れならカードを期限切れにする、など）。
// approval_already_decided は、別タブなどで先に決めた誰かのカードの最新状態を応答に持つので、
// あれば画面はそれでカードを差し替える。
// A failed approval API call; the screen branches on code (an expired card is shown as expired,
// etc.). approval_already_decided carries the card's latest state — settled elsewhere, e.g.
// another tab — when present, so the screen swaps its card with it.
export class ToolApprovalDecisionError extends Error {
  public readonly code: string;
  public readonly status: number;
  public readonly approval?: ToolApprovalApi;

  public constructor(message: string, code: string, status: number, approval?: ToolApprovalApi) {
    super(message);
    this.name = "ToolApprovalDecisionError";
    this.code = code;
    this.status = status;
    this.approval = approval;
  }
}

// 承認カードの決定を送り、更新後のカードを返す。CSRF は同一オリジンの fetch ラッパーが付ける。
// 状態を変える要求なので resilientFetch も自動再送はしない。
// Send the decision for an approval card and return the updated card. The same-origin fetch wrapper
// attaches CSRF, and resilientFetch never retries this state-changing request.
export async function decideToolApproval(
  approvalId: string,
  decision: ToolApprovalDecision,
  fallbackMessage: string,
  fetchImpl: FetchImpl = resilientFetch,
): Promise<ToolApprovalApi> {
  const { response, payload } = await fetchJson<unknown>(
    `/api/chat/tool-approvals/${encodeURIComponent(approvalId)}/decision`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision } satisfies ToolApprovalDecisionRequest),
    },
    fetchImpl,
  );
  if (!response.ok) {
    const code = isRecord(payload) && typeof payload.code === "string" ? payload.code : "";
    const approval = isRecord(payload) ? normalizeToolApproval(payload.approval) : undefined;
    throw new ToolApprovalDecisionError(
      extractApiErrorMessage(payload, fallbackMessage, response.status),
      code,
      response.status,
      approval,
    );
  }
  const parsed = ToolApprovalDecisionResponseSchema.safeParse(payload);
  const approval = parsed.success ? normalizeToolApproval(parsed.data.approval) : undefined;
  if (!approval) throw new ToolApprovalDecisionError(fallbackMessage, "invalid_response", response.status);
  return approval;
}
