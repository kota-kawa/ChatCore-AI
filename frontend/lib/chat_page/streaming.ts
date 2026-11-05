// SSE の 1 ブロック（event: / id: / data: の行）を、イベント名・ID・JSON データを持つ StreamParsedEvent へ変換する。
// Parses one SSE block (event: / id: / data: lines) into a StreamParsedEvent with event name, id and JSON data.
// Used by lib/chat_page/generation_stream_consumer.ts.

import { parseJsonText } from "../../scripts/core/runtime_validation";
import type { StreamParsedEvent } from "./types";

function isStreamData(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

// data 行が無い、または JSON が壊れているブロックは null を返して読み飛ばせるようにする。id は正の整数のときだけ採用する。
// Returns null for blocks without data lines or with broken JSON so callers can skip them; id is kept only when it is a positive integer.
export function parseStreamEventBlock(block: string): StreamParsedEvent | null {
  const lines = block
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0);

  if (lines.length === 0) return null;

  let event = "message";
  let eventId: number | undefined;
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      return;
    }
    if (line.startsWith("id:")) {
      const parsedId = Number.parseInt(line.slice(3).trim(), 10);
      if (Number.isFinite(parsedId) && parsedId > 0) {
        eventId = parsedId;
      }
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  if (dataLines.length === 0) return null;

  try {
    const parsed = parseJsonText(dataLines.join("\n"));
    if (!isStreamData(parsed)) return null;
    return {
      event,
      id: eventId,
      data: parsed,
    };
  } catch {
    return null;
  }
}
