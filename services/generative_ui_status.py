# 生成UIの成否を、機械可読な状態と理由コードとして表す。
# 失敗が本文の残骸や空のiframeとして「成功に見える」状態をなくすため、抽出・検証・修復の
# 各段階の結果をこの限られた語彙へ集約し、SSE・履歴・テレメトリで同じ語を使う。
# ユーザー入力やモデル出力の本文はここに載せない（理由コードは固定語彙のみ）。
# Represents the outcome of generated UI as a machine-readable state and reason code.
# Failures used to look like success: leftover prose, or an empty iframe. Every stage
# (extraction, validation, repair) folds its result into this small vocabulary, which is
# shared by SSE, history, and telemetry. No prompt or model text is ever carried here.

from __future__ import annotations

from typing import Any

ARTIFACT_STATUS_PART_TYPE = "artifact_status"

# 内部状態: 生成パイプラインが到達した段階を表す。
# Internal statuses describing where the generation pipeline ended up.
ARTIFACT_STATUS_NOT_REQUESTED = "not_requested"
ARTIFACT_STATUS_VALID = "valid"
ARTIFACT_STATUS_MISSING = "missing"
ARTIFACT_STATUS_INVALID = "invalid"
ARTIFACT_STATUS_SUPPRESSED = "suppressed"
ARTIFACT_STATUS_REPAIR_FAILED = "repair_failed"

# 理由コード: 固定語彙。ログとフロントの表示分岐の両方がこの語を読む。
# Reason codes: a fixed vocabulary read by both logs and the frontend.
REASON_EXPLICIT_OPT_OUT = "explicit_ui_opt_out"
REASON_REQUIRED_ARTIFACT_MISSING = "required_artifact_missing"
REASON_ARTIFACT_MALFORMED = "artifact_malformed"
REASON_ARTIFACT_VALIDATION_FAILED = "artifact_validation_failed"
REASON_ARTIFACT_QUALITY_INSUFFICIENT = "artifact_quality_insufficient"
REASON_REPAIR_FAILED = "artifact_repair_failed"
REASON_REPAIR_INVALID = "artifact_repair_invalid"
REASON_REPAIR_OUTPUT_LIMITED = "artifact_repair_output_limited"

# クライアントへ渡す状態。内部状態よりも粗く、表示の分岐に必要な粒度だけを持つ。
# Client-facing states: coarser than the internal statuses, at the granularity the UI needs.
CLIENT_STATE_ACCEPTED = "accepted"
CLIENT_STATE_REPAIRED = "repaired"
CLIENT_STATE_REJECTED = "rejected"
CLIENT_STATE_FAILED = "failed"

# 利用者に「作れなかった」と伝えるべき状態。成功状態は通知だけで、本文へは差し込まない。
# States the user must be told about; successful states are reported but not rendered.
USER_VISIBLE_CLIENT_STATES = frozenset({CLIENT_STATE_REJECTED, CLIENT_STATE_FAILED})

_CLIENT_STATES = {
    ARTIFACT_STATUS_VALID: CLIENT_STATE_ACCEPTED,
    ARTIFACT_STATUS_MISSING: CLIENT_STATE_REJECTED,
    ARTIFACT_STATUS_INVALID: CLIENT_STATE_REJECTED,
    ARTIFACT_STATUS_REPAIR_FAILED: CLIENT_STATE_FAILED,
}


def artifact_status_payload(
    status: str,
    reason_codes: list[str] | None = None,
    *,
    repair_attempted: bool = False,
) -> dict[str, str] | None:
    """Render one internal status as the client-facing ``{state, reason_code}`` pair.

    報告する必要のない状態（未要求・ユーザーの明示拒否）では ``None`` を返す。
    Returns ``None`` for statuses that need no report (not requested, explicit opt-out).
    """
    state = _CLIENT_STATES.get(status)
    if state is None:
        return None
    if state == CLIENT_STATE_ACCEPTED and repair_attempted:
        state = CLIENT_STATE_REPAIRED
    codes = [code for code in (reason_codes or []) if code]
    return {"state": state, "reason_code": codes[0] if codes else status}


def artifact_status_part(payload: dict[str, str] | None) -> dict[str, Any] | None:
    """Build the message part that tells the user a generated UI could not be shown."""
    if not payload or payload.get("state") not in USER_VISIBLE_CLIENT_STATES:
        return None
    return {"type": ARTIFACT_STATUS_PART_TYPE, "status": dict(payload)}


_REASON_CODE_RE = __import__("re").compile(r"[^a-z0-9_.-]+")
MAX_REASON_CODE_CHARS = 80


def normalize_artifact_status_part(raw: Any) -> dict[str, Any] | None:
    """Validate one stored ``artifact_status`` part on the history round trip.

    保存済みの状態も語彙の範囲だけを通す。理由コードは固定語彙のはずだが、
    古い保存や外部由来の値が本文を運ばないよう、ここで形を強制する。
    Stored statuses are re-checked against the vocabulary. Reason codes are meant to be
    fixed tokens; the shape is enforced here so no old or foreign value carries prose.
    """
    if not isinstance(raw, dict):
        return None
    status = raw.get("status") if isinstance(raw.get("status"), dict) else raw
    state = str(status.get("state") or "").strip()
    if state not in USER_VISIBLE_CLIENT_STATES:
        return None
    reason_code = _REASON_CODE_RE.sub(
        "_", str(status.get("reason_code") or "").strip().lower()
    ).strip("_")[:MAX_REASON_CODE_CHARS]
    return {
        "type": ARTIFACT_STATUS_PART_TYPE,
        "status": {"state": state, "reason_code": reason_code or state},
    }
