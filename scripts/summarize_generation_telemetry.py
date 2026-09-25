#!/usr/bin/env python3
# 生成テレメトリの構造化ログを集計し、チャット出力の変更前後で比べられる数値にする。
# ログ1行はターンの途中経過も含むため、request_id ごとに1件へ畳んでから数える。
# Aggregates the structured generation-telemetry logs into numbers that can be compared
# before and after a chat-output change. A turn writes several lines, so records are folded
# per request_id before counting.

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ターンの最後に必ず出るキー。これを持つ行があれば、その行がそのターンの確定値。
# The key a finished turn always logs; when present, that line holds the turn's final counters.
TERMINAL_EVENT_KEY = "terminal_event"

# テレメトリ行の判別に使うキー。どのターンでも必ず含まれる。
# The key that identifies a telemetry line; every telemetry payload carries it.
TELEMETRY_MARKER_KEY = "first_pass_finish_reason"

DEFAULT_LOG_PATH = Path("logs/app.log")

# ターンを閉じるログのメッセージ。request_id が付かない古いログを数えるときに使う。
# 生成スレッドへリクエストコンテキストを伝播する修正より前のログは、全行が request_id="-"
# で届くため、行を畳めない。その場合はターンを閉じた行だけを1ターンとして数える。
# Messages that close a turn, used for logs whose lines carry no request id. Before request
# context was carried into the generation thread every line arrived with request_id="-", so
# such lines cannot be folded; only the closing line is counted as a turn.
TURN_CLOSING_MESSAGE_PREFIXES = (
    "Chat generation completed.",
    "Chat generation ended with a persisted partial answer.",
    "Chat generation ended without a terminal event",
    "Chat generation produced an empty response.",
    "Chat generation stopped due to",
    "Chat generation stopped because",
    "Chat generation hit an LLM provider rate limit",
    "Unexpected error while generating chat response.",
    # "Failed to prepare the chat generation turn." はここに入れない。ターン状態の構築に
    # 失敗した経路では、その直後に必ず "Chat generation ended without a terminal event" が
    # 続くため、両方を数えると1ターンが2件になる。
    # "Failed to prepare the chat generation turn." is deliberately absent: that path always
    # logs "Chat generation ended without a terminal event" right after it, so counting both
    # would turn one turn into two.
)


# 率として報告する真偽値・カウンタ。ターン単位で「1回でも起きたか」を数える。
# Boolean and counter fields reported as rates: how many turns saw them at least once.
OCCURRENCE_FIELDS = (
    "continuation_stalled",
    "continuation_restart_trimmed",
    "llm_turn_budget_exhausted",
    "tools_withdrawn_by_budget",
    "empty_answer_recoveries",
    "missing_turn_state_updates",
    "untagged_turn_state_recoveries",
    "tool_schema_recoveries",
    "tool_schema_retries",
    "research_failure_recoveries",
    "salvaged_partial_answers",
    "input_limit_recoveries",
    "research_output_limit_recoveries",
    "truncated_evidence_payloads",
    "artifact_repair_attempted",
    "artifact_repair_succeeded",
    # 利用者のデータ（メモなど）のツール。承認待ちで締めたターン、外部の内容で自動承認を止めたターン、
    # 引数の不備、提案・自動実行・読み取りがあったターンの割合。
    # The user-data (memo) tools: turns closed on a pending approval, turns whose auto approval
    # was held back by external content, argument rejections, and turns with proposals, auto
    # runs or reads.
    "approval_pending_turn",
    "auto_approval_suppressed_by_untrusted_input",
    "workspace_invalid_arguments",
    "workspace_write_proposals",
    "workspace_auto_executions",
    "workspace_read_calls",
)

# 中央値で報告する分量の指標。
# Size metrics reported as medians.
MEDIAN_FIELDS = (
    "llm_turns",
    "tool_calls",
    "web_search_count",
    "continuation_count",
    "final_answer_input_tokens",
    "final_answer_output_chars",
    "duration_seconds",
)


@dataclass
class Turn:
    """1ターン分に畳んだテレメトリ。"""

    request_id: str
    outcome: str
    payload: dict[str, Any] = field(default_factory=dict)


def _iter_log_lines(paths: Iterable[Path], since: str = "") -> Iterator[dict[str, Any]]:
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                # タイムスタンプは ISO 8601 なので、文字列比較で期間を絞れる。
                # Timestamps are ISO 8601, so a string comparison is enough to filter by time.
                if since and str(record.get("timestamp") or "") < since:
                    continue
                yield record


def _telemetry_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    extra = record.get("extra")
    if not isinstance(extra, dict) or TELEMETRY_MARKER_KEY not in extra:
        return None
    return extra


def _closes_a_turn(record: dict[str, Any], payload: dict[str, Any]) -> bool:
    if payload.get(TERMINAL_EVENT_KEY):
        return True
    message = str(record.get("message") or "")
    return message.startswith(TURN_CLOSING_MESSAGE_PREFIXES)


def collect_turns(records: Iterable[dict[str, Any]]) -> tuple[list[Turn], int]:
    # request_id が付いている行は、その ID ごとに畳む（終了行があればそれを採用）。
    # 付いていない行は畳めないので、ターンを閉じた行だけを1ターンとして数える。
    # Lines that carry a request id are folded per id, preferring the terminal line. Lines
    # without one cannot be folded, so only the line that closed the turn counts as a turn.
    turns: dict[str, Turn] = {}
    uncorrelated: list[Turn] = []
    uncorrelated_lines = 0

    for record in records:
        payload = _telemetry_payload(record)
        if payload is None:
            continue

        terminal_event = payload.get(TERMINAL_EVENT_KEY)
        outcome = str(terminal_event) if terminal_event else "error"
        request_id = str(record.get("request_id") or "")

        if not request_id or request_id == "-":
            uncorrelated_lines += 1
            if _closes_a_turn(record, payload):
                uncorrelated.append(Turn(request_id="-", outcome=outcome, payload=dict(payload)))
            continue

        existing = turns.get(request_id)
        if existing is not None and existing.outcome in {"done", "incomplete"}:
            continue

        turns[request_id] = Turn(request_id=request_id, outcome=outcome, payload=dict(payload))

    return [*turns.values(), *uncorrelated], uncorrelated_lines


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value != ""
    if isinstance(value, list):
        return bool(value)
    return False


def summarize(turns: list[Turn], uncorrelated_lines: int = 0) -> dict[str, Any]:
    total = len(turns)
    summary: dict[str, Any] = {
        "turns": total,
        "uncorrelated_lines": uncorrelated_lines,
        "outcomes": dict(Counter(turn.outcome for turn in turns)),
        "models": dict(Counter(str(turn.payload.get("model") or "(unknown)") for turn in turns)),
        "first_pass_finish_reason": dict(
            Counter(str(turn.payload.get("first_pass_finish_reason") or "(none)") for turn in turns)
        ),
        "artifact_status": dict(
            Counter(str(turn.payload.get("artifact_status") or "(none)") for turn in turns)
        ),
        "artifact_reason_codes": dict(
            Counter(
                code
                for turn in turns
                for code in turn.payload.get("artifact_reason_codes", [])
                if isinstance(code, str)
            )
        ),
        "continuation_reasons": dict(
            Counter(
                reason
                for turn in turns
                for reason in turn.payload.get("continuation_reasons", [])
                if isinstance(reason, str)
            )
        ),
        # ツール呼び出しの拒否を「理由:拒否文にあったツール名」で数える。
        # Tool-call rejections counted as "reason:tool the rejection named".
        "tool_schema_rejections": dict(
            Counter(
                f"{entry.get('reason') or 'other'}:{entry.get('tool') or '(none)'}"
                for turn in turns
                for entry in turn.payload.get("tool_schema_rejections", [])
                if isinstance(entry, dict)
            )
        ),
        "occurrence_rates": {},
        "medians": {},
    }

    for name in OCCURRENCE_FIELDS:
        hits = sum(1 for turn in turns if _truthy(turn.payload.get(name)))
        summary["occurrence_rates"][name] = {
            "turns": hits,
            "rate": round(hits / total, 4) if total else 0.0,
        }

    for name in MEDIAN_FIELDS:
        values = [
            value
            for turn in turns
            if (value := _numeric(turn.payload.get(name))) is not None
        ]
        summary["medians"][name] = _median(values)

    return summary


def _format_counter(title: str, counts: dict[str, int], total: int) -> list[str]:
    if not counts:
        return [f"{title}: (なし)"]
    lines = [f"{title}:"]
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        share = f" ({count / total:.1%})" if total else ""
        lines.append(f"  {key}: {count}{share}")
    return lines


def render_text(summary: dict[str, Any]) -> str:
    total = int(summary["turns"])
    lines = [f"集計したターン数: {total}"]
    if summary.get("uncorrelated_lines"):
        lines.append(
            f"※ request_id の無いテレメトリ行が {summary['uncorrelated_lines']} 件ありました。"
            "生成スレッドへリクエストコンテキストを伝播する修正より前のログです。"
            "その範囲はターンを閉じた行だけを数えています。"
        )
    if total == 0:
        lines.append("テレメトリを含むログ行が見つかりませんでした。")
        return "\n".join(lines)

    lines += _format_counter("結果", summary["outcomes"], total)
    lines += _format_counter("モデル", summary["models"], total)
    lines += _format_counter("初回パスの終了理由", summary["first_pass_finish_reason"], total)
    lines += _format_counter("生成UIの状態", summary["artifact_status"], total)
    lines += _format_counter("生成UIの理由コード", summary["artifact_reason_codes"], total)
    lines += _format_counter("継続生成の理由", summary["continuation_reasons"], total)
    lines += _format_counter("ツール呼び出しの拒否", summary.get("tool_schema_rejections", {}), total)

    lines.append("発生率（1ターンに1回でも起きた割合）:")
    for name, stats in summary["occurrence_rates"].items():
        lines.append(f"  {name}: {stats['turns']} ({stats['rate']:.1%})")

    lines.append("中央値:")
    for name, value in summary["medians"].items():
        lines.append(f"  {name}: {'-' if value is None else value}")

    return "\n".join(lines)


def _rate(counts: dict[str, int], key: str, total: int) -> float:
    return counts.get(key, 0) / total if total else 0.0


def _delta(before: float, after: float) -> str:
    # 率の差はポイントで表す。1.5% と 3.0% の差は「1.5 ポイント」であって「倍」ではない。
    # Rate differences are reported in points: 1.5% vs 3.0% differs by 1.5 points, not by 100%.
    diff = (after - before) * 100
    if abs(diff) < 0.05:
        return "±0"
    return f"{diff:+.1f}pt"


def render_comparison(before: dict[str, Any], after: dict[str, Any], show_all: bool = False) -> str:
    # 変更前後を1行ずつ並べる。悪化した指標を探すための表なので、率と中央値だけを出す。
    # One row per metric, before and after: the table exists to spot regressions, so it
    # reports rates and medians only.
    before_total = int(before["turns"])
    after_total = int(after["turns"])
    lines = [f"ターン数: 変更前 {before_total} → 変更後 {after_total}"]
    uncorrelated = int(before.get("uncorrelated_lines", 0)) + int(after.get("uncorrelated_lines", 0))
    if uncorrelated:
        lines.append(
            f"※ request_id の無いテレメトリ行が合計 {uncorrelated} 件ありました。"
            "その範囲はターンを閉じた行だけを数えています。"
        )
    lines.append("")
    lines.append(f"{'指標':<34} {'変更前':>10} {'変更後':>10} {'差':>10}")

    for outcome in sorted(set(before["outcomes"]) | set(after["outcomes"])):
        before_rate = _rate(before["outcomes"], outcome, before_total)
        after_rate = _rate(after["outcomes"], outcome, after_total)
        lines.append(
            f"{'結果:' + outcome:<34} {before_rate:>9.1%} {after_rate:>9.1%} "
            f"{_delta(before_rate, after_rate):>10}"
        )

    for reason in sorted(set(before["first_pass_finish_reason"]) | set(after["first_pass_finish_reason"])):
        before_rate = _rate(before["first_pass_finish_reason"], reason, before_total)
        after_rate = _rate(after["first_pass_finish_reason"], reason, after_total)
        lines.append(
            f"{'初回終了:' + reason:<34} {before_rate:>9.1%} {after_rate:>9.1%} "
            f"{_delta(before_rate, after_rate):>10}"
        )

    hidden = 0
    for name in OCCURRENCE_FIELDS:
        before_rate = float(before["occurrence_rates"][name]["rate"])
        after_rate = float(after["occurrence_rates"][name]["rate"])
        # 変更前後とも0の指標は、表を読みにくくするだけなので既定では隠す。
        # Metrics that never fired on either side only crowd the table, so they are hidden.
        if not show_all and before_rate == 0.0 and after_rate == 0.0:
            hidden += 1
            continue
        lines.append(
            f"{name:<34} {before_rate:>9.1%} {after_rate:>9.1%} {_delta(before_rate, after_rate):>10}"
        )
    if hidden:
        lines.append(f"（変更前後とも0件の指標 {hidden} 件は省略。--all で表示）")

    for name in MEDIAN_FIELDS:
        before_value = before["medians"][name]
        after_value = after["medians"][name]
        before_text = "-" if before_value is None else f"{before_value:.1f}"
        after_text = "-" if after_value is None else f"{after_value:.1f}"
        diff_text = (
            "-"
            if before_value is None or after_value is None
            else f"{after_value - before_value:+.1f}"
        )
        lines.append(f"{'中央値:' + name:<34} {before_text:>10} {after_text:>10} {diff_text:>10}")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "生成テレメトリの構造化ログを集計する。"
            " チャット出力に関わる変更の前後で同じ入力を流し、この出力を並べて比べる。"
        )
    )
    parser.add_argument(
        "logs",
        nargs="*",
        type=Path,
        default=[DEFAULT_LOG_PATH],
        help=f"集計するログファイル（既定: {DEFAULT_LOG_PATH}）",
    )
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    parser.add_argument(
        "--baseline",
        type=Path,
        action="append",
        default=None,
        help="変更前のログ。指定すると変更前→変更後の差分を出す（複数指定可）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="変更前後とも0件の指標も表示する（--baseline と併用）",
    )
    parser.add_argument(
        "--since",
        default="",
        help="この時刻以降の行だけを集計する（例: 2026-09-22T00:00:00）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = list(args.logs)
    baseline_paths = list(args.baseline or [])
    missing = [path for path in [*paths, *baseline_paths] if not path.is_file()]
    if missing:
        for path in missing:
            print(f"ログファイルが見つかりません: {path}", file=sys.stderr)
        return 1

    summary = summarize(*collect_turns(_iter_log_lines(paths, args.since)))
    if not baseline_paths:
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else render_text(summary))
        return 0

    baseline = summarize(*collect_turns(_iter_log_lines(baseline_paths, args.since)))
    if args.json:
        print(json.dumps({"before": baseline, "after": summary}, ensure_ascii=False, indent=2))
    else:
        print(render_comparison(baseline, summary, show_all=args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
