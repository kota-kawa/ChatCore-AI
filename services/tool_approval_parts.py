# チャットの承認カード（tool_approval パーツ）の契約を持つ。書き込みツールはその場で実行せず、
# 承認待ちとしてサーバーに保存し、回答の末尾にこのカードを付けて利用者に決めてもらう。
# カードの形は services/response_models.py の ToolApprovalApi が正本で、承認 API の応答と同じ形を使う。
# Owns the contract of chat approval cards (the tool_approval part). Write tools do not run on the spot:
# the server stores a pending action and appends this card to the reply so the user decides.
# ToolApprovalApi in services/response_models.py is the source of truth, shared with the approval API.

from __future__ import annotations

from html import escape as escape_html
from typing import Any, get_args

from pydantic import ValidationError

from services.response_models import ToolApprovalApi, ToolApprovalDecision, ToolApprovalStatus

TOOL_APPROVAL_PART_TYPE = "tool_approval"
# DB の CHECK 制約はこの値の集合から作り、応答モデルの Literal とずれないようにする。
# DB CHECK constraints are built from these sets so they never drift from the response model literals.
TOOL_APPROVAL_STATUSES: tuple[str, ...] = get_args(ToolApprovalStatus)
TOOL_APPROVAL_DECISIONS: tuple[str, ...] = get_args(ToolApprovalDecision)


class ToolApprovalValidationError(ValueError):
    """Raised when an approval-card payload does not satisfy the contract."""


# 承認カードの中身を検証し、保存・配信する形の辞書で返す。
# Validate an approval-card payload and return the dict that is stored and delivered.
def validate_tool_approval_payload(payload: Any) -> dict[str, Any]:
    try:
        approval = ToolApprovalApi.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise ToolApprovalValidationError(str(exc)) from exc
    return approval.model_dump(exclude_none=True)


# 検証済みの承認カードを、メッセージの表示部品へ変換する。
# Turn a validated approval card into a message display part.
def tool_approval_part(approval: dict[str, Any]) -> dict[str, Any]:
    return {"type": TOOL_APPROVAL_PART_TYPE, "approval": approval}


# 後続ターンのモデル文脈へ渡す要約行を作る。何を提案し、どう決まったかだけを伝え、
# メモの本文や差分は入れない（利用者が承認していない本文を事実として読ませないため）。
# Build the summary lines handed to later turns: what was proposed and how it ended, never the memo
# body or diff, so text the user did not approve is not read back as fact.
def describe_tool_approval_for_context(approval: Any) -> list[str]:
    if not isinstance(approval, dict):
        return []
    tool = str(approval.get("tool") or "").strip()
    status = str(approval.get("status") or "").strip()
    if not tool or not status:
        return []
    lines = [f'<tool_approval tool="{escape_html(tool)}" status="{escape_html(status)}">']
    target = _target_title(approval.get("preview"))
    if target:
        lines.append(f"<target>{escape_html(target)}</target>")
    result = _result_summary(approval.get("result"))
    if result:
        lines.append(f"<result>{escape_html(result)}</result>")
    lines.append("</tool_approval>")
    return lines


# 共有表示と fork 用に、提案の中身・結果・警告を落として読み取り専用にする。
# 共有相手に非公開のメモ本文や差分を見せず、他人のカードを操作させないため。
# Strip the proposal, result and warnings and mark the card readonly for shared views and forks, so
# viewers never see private memo text or diffs and cannot act on someone else's card.
def redact_tool_approval_for_share(approval: dict[str, Any]) -> dict[str, Any]:
    redacted = {
        key: approval[key]
        for key in ("id", "tool", "family", "status", "decision")
        if approval.get(key) is not None
    }
    redacted["readonly"] = True
    return redacted


# 提案の対象の題名。作成なら新しいメモの題名、追記・書き換えなら対象メモの題名。
# Title of the proposal's target: the new memo's title for a create, the target memo's for the rest.
def _target_title(preview: Any) -> str:
    if not isinstance(preview, dict):
        return ""
    title = preview.get("title") if preview.get("kind") == "memo_create" else preview.get("memo_title")
    return str(title or "").strip()


# 実行結果を1行にする。失敗なら理由のコード、成功なら対象の ID。
# Summarize the outcome in one line: the reason code on failure, the target id on success.
def _result_summary(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("error_code"):
        return f"error_code={result['error_code']}"
    if result.get("target_id") is not None:
        return f"target_id={result['target_id']}"
    return ""
