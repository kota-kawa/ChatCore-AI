import type { ContentFormat, MediaType, PromptResource } from "./types";

export const GUEST_POST_CONTENT_FORMAT: ContentFormat = "prompt";
export const GUEST_POST_MEDIA_TYPE: MediaType = "text";

type BuildPromptCreateFormDataOptions = {
  isGuest: boolean;
  title: string;
  category: string;
  content: string;
  description?: string;
  contentFormat: ContentFormat;
  mediaType: MediaType;
  inputExamples: string;
  outputExamples: string;
  aiModel: string;
  attributes: Record<string, string>;
  resources: PromptResource[];
  referenceImageFile: File | null;
};

// ゲスト投稿ではリンクを許可しない。サーバー側の検証に先立ち、入力直後に分かりやすく案内する。
// Guest posts do not allow links. This gives immediate feedback before server-side validation.
const URL_PATTERN = /(?:https?:\/\/|www\.)[^\s<>"']+/i;

export function containsGuestPostUrl(...values: string[]): boolean {
  return values.some((value) => URL_PATTERN.test(value));
}

// 投稿データを組み立てる。ゲストのときは、呼び出し元の状態に関係なくテキスト投稿の最小契約へ固定する。
// Build the post payload. Guest submissions are forced to the minimum text-only contract,
// regardless of any stale state held by the caller.
export function buildPromptCreateFormData({
  isGuest,
  title,
  category,
  content,
  description,
  contentFormat,
  mediaType,
  inputExamples,
  outputExamples,
  aiModel,
  attributes,
  resources,
  referenceImageFile
}: BuildPromptCreateFormDataOptions): FormData {
  const formData = new FormData();
  const resolvedContentFormat = isGuest ? GUEST_POST_CONTENT_FORMAT : contentFormat;
  const resolvedMediaType = isGuest ? GUEST_POST_MEDIA_TYPE : mediaType;

  formData.append("title", title);
  formData.append("category", isGuest ? "" : category);
  formData.append("content", content);
  formData.append("description", description || "");
  formData.append("content_format", resolvedContentFormat);
  formData.append("media_type", resolvedMediaType);
  formData.append("input_examples", isGuest ? "" : inputExamples);
  formData.append("output_examples", isGuest ? "" : outputExamples);
  formData.append("ai_model", isGuest ? "" : aiModel);
  formData.append("attributes", JSON.stringify(isGuest ? {} : attributes));
  formData.append("resources", JSON.stringify(isGuest ? [] : resources));

  if (!isGuest && referenceImageFile) {
    formData.append("reference_image", referenceImageFile);
  }

  return formData;
}
