import contextlib
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_generation_telemetry import (
    collect_turns,
    main,
    render_comparison,
    summarize,
)
from services.chat_generation_telemetry import ChatGenerationTelemetry
from services.logging_config import JsonLogFormatter


def _log_line(request_id: str, message: str, extra: dict) -> str:
    # 実際のフォーマッタでログ行を作る。集計側がログの形に追随できているかを確かめるため。
    # Build the line with the real formatter so the summary is tested against the real log shape.
    record = logging.LogRecord(
        "services.chat_generation", logging.INFO, "chat_generation.py", 1, message, None, None
    )
    record.request_id = request_id
    for key, value in extra.items():
        setattr(record, key, value)
    return JsonLogFormatter().format(record)


def _completed_turn(request_id: str, **fields) -> list[str]:
    telemetry = ChatGenerationTelemetry(model=fields.pop("model", "claude-haiku-4-5"))
    telemetry.first_pass_finish_reason = fields.pop("first_pass_finish_reason", "stop")
    for name, value in fields.items():
        setattr(telemetry, name, value)
    payload = telemetry.as_log_extra()
    return [
        _log_line(request_id, "Chat generation step.", payload),
        _log_line(
            request_id,
            "Chat generation completed.",
            {"terminal_event": "done", "duration_seconds": 10.0, **payload},
        ),
    ]


def _failed_turn(request_id: str, **fields) -> list[str]:
    telemetry = ChatGenerationTelemetry(model=fields.pop("model", "claude-haiku-4-5"))
    telemetry.first_pass_finish_reason = ""
    for name, value in fields.items():
        setattr(telemetry, name, value)
    return [
        _log_line(request_id, "Chat generation produced an empty response.", telemetry.as_log_extra())
    ]


class SummarizeGenerationTelemetryTestCase(unittest.TestCase):
    """
    生成テレメトリのログ集計が、ターン単位の数値を正しく畳むことを検証するテストケースクラス
    Test case class verifying the telemetry log summary folds log lines into per-turn numbers.
    """

    def _summary_of(self, lines: list[str]) -> dict:
        records = [json.loads(line) for line in lines]
        return summarize(collect_turns(records))

    def test_a_turn_is_counted_once_even_though_it_logs_several_lines(self):
        """
        1ターンが複数行を出しても、集計では1件として数えられることを検証します。
        Verify a turn that writes several log lines is still counted once.
        """
        summary = self._summary_of(_completed_turn("req-1", llm_turns=3))

        self.assertEqual(summary["turns"], 1)
        self.assertEqual(summary["outcomes"], {"done": 1})

    def test_a_turn_without_a_terminal_event_counts_as_an_error(self):
        """
        終了イベントを出さずに終わったターンが、失敗として数えられることを検証します。
        Verify a turn that never logged a terminal event is counted as an error.
        """
        summary = self._summary_of(_failed_turn("req-2", empty_answer_recoveries=1))

        self.assertEqual(summary["outcomes"], {"error": 1})
        self.assertEqual(summary["occurrence_rates"]["empty_answer_recoveries"]["turns"], 1)

    def test_rates_and_medians_are_computed_over_turns(self):
        """
        発生率と中央値が、行数ではなくターン数を分母に計算されることを検証します。
        Verify rates and medians are computed over turns rather than over log lines.
        """
        lines = [
            *_completed_turn("req-1", first_pass_finish_reason="length", continuation_count=2),
            *_completed_turn("req-2", continuation_count=0),
            *_failed_turn("req-3", tool_schema_recoveries=1),
        ]

        summary = self._summary_of(lines)

        self.assertEqual(summary["turns"], 3)
        self.assertEqual(summary["first_pass_finish_reason"]["length"], 1)
        self.assertEqual(summary["occurrence_rates"]["tool_schema_recoveries"]["rate"], round(1 / 3, 4))
        self.assertEqual(summary["medians"]["continuation_count"], 0.0)

    def test_lines_without_telemetry_are_ignored(self):
        """
        テレメトリを含まないログ行が集計対象にならないことを検証します。
        Verify log lines that carry no telemetry payload are left out of the summary.
        """
        lines = [_log_line("req-9", "Request finished.", {"status_code": 200})]

        self.assertEqual(self._summary_of(lines)["turns"], 0)

    def test_comparison_reports_rate_differences_in_points(self):
        """
        変更前後の比較が、率の差をポイントで表すことを検証します。
        Verify the before/after comparison reports rate differences in points.
        """
        before = self._summary_of(
            [*_completed_turn("a-1"), *_completed_turn("a-2"), *_completed_turn("a-3"), *_completed_turn("a-4")]
        )
        after = self._summary_of(
            [*_completed_turn("b-1"), *_completed_turn("b-2"), *_completed_turn("b-3"), *_failed_turn("b-4")]
        )

        table = render_comparison(before, after)

        self.assertIn("結果:error", table)
        self.assertIn("+25.0pt", table)

    def test_cli_reads_a_log_file_and_filters_by_time(self):
        """
        コマンドが実ファイルを読み、--since で期間を絞れることを検証します。
        Verify the command reads a log file and narrows the range with --since.
        """
        lines = [*_completed_turn("req-1"), *_failed_turn("req-2")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(main([str(path), "--json"]), 0)
            self.assertEqual(json.loads(captured.getvalue())["turns"], 2)

            # 未来の時刻で絞れば、同じファイルから1件も残らない。
            # Filtering from a future timestamp leaves nothing from the same file.
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(main([str(path), "--since", "2999-01-01T00:00:00", "--json"]), 0)
            self.assertEqual(json.loads(captured.getvalue())["turns"], 0)

    def test_cli_reports_a_missing_log_file(self):
        """
        指定したログファイルが無いとき、エラー終了することを検証します。
        Verify the command exits with an error when the log file does not exist.
        """
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(Path(directory) / "missing.log")]), 1)


if __name__ == "__main__":
    unittest.main()
