import { parseJsonText } from "../../scripts/core/runtime_validation";
import type { StreamParsedEvent } from "./types";

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
    if (!parsed || typeof parsed !== "object") return null;
    return {
      event,
      id: eventId,
      data: parsed as Record<string, unknown>,
    };
  } catch {
    return null;
  }
}
