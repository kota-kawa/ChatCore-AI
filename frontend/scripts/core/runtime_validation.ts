import { ApiErrorPayloadSchema } from "../../types/chat";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseJsonText(raw: string): unknown {
  return JSON.parse(raw);
}

async function readJsonBody(response: Response): Promise<unknown> {
  const payload: unknown = await response.json();
  return payload;
}

function extractApiErrorMessage(
  payload: unknown,
  defaultMessage: string,
  fallbackStatus?: number
) {
  if (typeof payload === "string" && payload.trim()) return payload.trim();

  const parsed = ApiErrorPayloadSchema.safeParse(payload);
  if (parsed.success) {
    const { error, message, detail } = parsed.data;
    const directMessage = [error, message].find((value) => typeof value === "string" && value.trim());
    if (directMessage) {
      return directMessage.trim();
    }

    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }

    if (Array.isArray(detail) && detail.length > 0) {
      const firstDetail = detail[0];
      if (typeof firstDetail === "string" && firstDetail.trim()) {
        return firstDetail.trim();
      }
      if (isRecord(firstDetail) && typeof firstDetail.msg === "string" && firstDetail.msg.trim()) {
        return firstDetail.msg.trim();
      }
    }
  }

  if (fallbackStatus) {
    return `サーバーエラー: ${fallbackStatus}`;
  }
  return defaultMessage;
}

export { extractApiErrorMessage, isRecord, parseJsonText, readJsonBody };
