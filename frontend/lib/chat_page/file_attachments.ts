import {
  CHAT_IMAGE_ACCEPT,
  downscaleChatImage,
  IMAGE_INPUT_MODEL_ONLY_MESSAGE,
  isImageAttachmentName,
  MAX_CHAT_IMAGE_BYTES,
  MAX_CHAT_IMAGE_SOURCE_BYTES,
  type DownscaledChatImage,
} from "./chat_images";
import type { AttachedFile } from "./types";

export const MAX_ATTACHED_FILES = 5;
export const MAX_ATTACHMENT_FILE_SIZE_BYTES = 1_048_576;
// バックエンドの上限に合わせる（services/attached_files.py の
// MAX_ATTACHED_FILE_CONTENT_LENGTH / MAX_ATTACHED_FILE_NAME 相当）。ここで弾かないと
// /api/chat が ValidationError になり、無関係なエラー文言だけが表示されて送信できない。
// Mirrors the backend limits (MAX_ATTACHED_FILE_CONTENT_LENGTH in
// services/attached_files.py and the name length in services/request_models.py).
// Without this check /api/chat fails validation and the user only sees an
// unrelated 400 message.
export const MAX_ATTACHMENT_TEXT_LENGTH = 100_000;
export const MAX_ATTACHMENT_NAME_LENGTH = 256;

export const CHAT_ATTACHMENT_ACCEPT = [
  ".txt",
  ".md",
  ".csv",
  ".json",
  ".xml",
  ".html",
  ".css",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".py",
  ".rb",
  ".go",
  ".rs",
  ".java",
  ".c",
  ".cpp",
  ".h",
  ".sh",
  ".yaml",
  ".yml",
  ".sql",
  ".log",
  ".ini",
  ".toml",
  ".env",
  ".gitignore",
  ".pdf",
  ".docx",
  ".xlsx",
  ".pptx",
].join(",");

// 画像を読めるモデルを選んでいるときだけ、ファイル選択で画像も選べるようにする。
// Offer images in the file picker only while a model that reads images is selected.
export function chatAttachmentAccept(allowImages: boolean): string {
  return allowImages ? `${CHAT_ATTACHMENT_ACCEPT},${CHAT_IMAGE_ACCEPT}` : CHAT_ATTACHMENT_ACCEPT;
}

const ACCEPTED_TEXT_FILE_TYPES = new Set([
  "text/plain",
  "text/markdown",
  "text/csv",
  "text/html",
  "text/css",
  "text/javascript",
  "text/xml",
  "application/json",
  "application/xml",
]);

const TEXT_EXTENSION_PATTERN =
  /\.(txt|md|csv|json|xml|html|css|js|ts|tsx|jsx|py|rb|go|rs|java|c|cpp|h|sh|yaml|yml|sql|log|ini|toml|env|gitignore)$/i;
const DOCUMENT_EXTENSION_PATTERN = /\.(pdf|docx|xlsx|pptx)$/i;

type FileLike = Pick<File, "name" | "type" | "size">;

export function isSupportedChatAttachment(file: FileLike): boolean {
  return (
    ACCEPTED_TEXT_FILE_TYPES.has(file.type) ||
    TEXT_EXTENSION_PATTERN.test(file.name) ||
    DOCUMENT_EXTENSION_PATTERN.test(file.name)
  );
}

function isDocumentChatAttachment(file: FileLike): boolean {
  return DOCUMENT_EXTENSION_PATTERN.test(file.name);
}

export function getAttachmentIconClass(fileName: string): string {
  const lowerName = fileName.toLowerCase();
  if (isImageAttachmentName(lowerName)) return "bi-file-earmark-image";
  if (lowerName.endsWith(".pdf")) return "bi-file-earmark-pdf";
  if (lowerName.endsWith(".docx")) return "bi-file-earmark-word";
  if (lowerName.endsWith(".xlsx")) return "bi-file-earmark-excel";
  if (lowerName.endsWith(".pptx")) return "bi-file-earmark-ppt";
  return "bi-file-earmark-text";
}

function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("ファイルを読み取れませんでした。"));
    reader.onload = (event) => {
      resolve(typeof event.target?.result === "string" ? event.target.result : "");
    };
    reader.readAsText(file, "utf-8");
  });
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("ファイルを読み取れませんでした。"));
    reader.onload = (event) => {
      const result = typeof event.target?.result === "string" ? event.target.result : "";
      const commaIndex = result.indexOf(",");
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

async function readChatAttachmentFile(file: File): Promise<AttachedFile> {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  if (isDocumentChatAttachment(file)) {
    return {
      id,
      name: file.name,
      size: file.size,
      mediaType: file.type,
      dataBase64: await readAsBase64(file),
    };
  }

  return {
    id,
    name: file.name,
    size: file.size,
    mediaType: file.type,
    content: await readAsText(file),
  };
}

export function mergeChatAttachments(previous: AttachedFile[], additions: AttachedFile[]): AttachedFile[] {
  if (additions.length === 0) return previous;
  const next = [...previous];
  const names = new Set(previous.map((file) => file.name));
  for (const addition of additions) {
    if (next.length >= MAX_ATTACHED_FILES) break;
    if (names.has(addition.name)) continue;
    names.add(addition.name);
    next.push(addition);
  }
  return next;
}

type ReadAttachmentOptions = {
  /** 画像を読めるモデルを選んでいるか / Whether the selected model reads images */
  allowImages: boolean;
  /** 画像の縮小処理。テストではブラウザの canvas の代わりを渡す / Image downscaler; tests pass a canvas stand-in */
  readImage?: (file: File) => Promise<DownscaledChatImage>;
};

async function readImageAttachment(
  file: File,
  readImage: (file: File) => Promise<DownscaledChatImage>,
): Promise<AttachedFile> {
  const image = await readImage(file);
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    size: image.size,
    mediaType: image.mediaType,
    dataBase64: image.dataBase64,
    previewUrl: `data:${image.mediaType};base64,${image.dataBase64}`,
  };
}

export async function readSelectedChatAttachments(
  files: File[],
  existingFiles: AttachedFile[],
  notifyError: (message: string) => void,
  { allowImages, readImage = downscaleChatImage }: ReadAttachmentOptions,
): Promise<AttachedFile[]> {
  const selected: AttachedFile[] = [];
  const names = new Set(existingFiles.map((file) => file.name));

  for (const file of files) {
    if (existingFiles.length + selected.length >= MAX_ATTACHED_FILES) {
      notifyError(`添付できるファイルは${MAX_ATTACHED_FILES}件までです。`);
      break;
    }

    if (names.has(file.name)) continue;

    if (file.name.length > MAX_ATTACHMENT_NAME_LENGTH) {
      notifyError(`「${file.name}」はファイル名が${MAX_ATTACHMENT_NAME_LENGTH}文字を超えるため添付できません。`);
      continue;
    }

    if (isImageAttachmentName(file.name)) {
      if (!allowImages) {
        notifyError(IMAGE_INPUT_MODEL_ONLY_MESSAGE);
        continue;
      }
      if (file.size > MAX_CHAT_IMAGE_SOURCE_BYTES) {
        notifyError(`「${file.name}」は${MAX_CHAT_IMAGE_SOURCE_BYTES / 1_048_576}MBを超えるため添付できません。`);
        continue;
      }
      try {
        const attachment = await readImageAttachment(file, readImage);
        if (attachment.size > MAX_CHAT_IMAGE_BYTES) {
          notifyError(`「${file.name}」は縮小しても${MAX_CHAT_IMAGE_BYTES / 1_048_576}MBを超えるため添付できません。`);
          continue;
        }
        selected.push(attachment);
        names.add(file.name);
      } catch {
        notifyError(`「${file.name}」を画像として読み取れませんでした。`);
      }
      continue;
    }

    if (file.size > MAX_ATTACHMENT_FILE_SIZE_BYTES) {
      notifyError(`「${file.name}」は1MBを超えるため添付できません。`);
      continue;
    }

    if (!isSupportedChatAttachment(file)) {
      notifyError(`「${file.name}」はサポートされていないファイル形式です。`);
      continue;
    }

    try {
      const attachment = await readChatAttachmentFile(file);
      // 1MB 以内でもテキストの文字数はサーバーの上限を超えうる（UTF-8 の1バイト文字が
      // 並ぶログなど）。ここで弾かないと送信時に無関係なエラーになる。
      // A file under 1MB can still exceed the server's character limit (e.g. a log
      // of single-byte characters). Rejecting it here avoids an unrelated error.
      if (typeof attachment.content === "string" && attachment.content.length > MAX_ATTACHMENT_TEXT_LENGTH) {
        notifyError(`「${file.name}」は本文が10万文字を超えるため添付できません。`);
        continue;
      }
      selected.push(attachment);
      names.add(file.name);
    } catch {
      notifyError(`「${file.name}」を読み取れませんでした。`);
    }
  }

  return selected;
}
