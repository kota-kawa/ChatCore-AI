import type { AttachedFile } from "./types";

export const MAX_ATTACHED_FILES = 5;
export const MAX_ATTACHMENT_FILE_SIZE_BYTES = 1_048_576;

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

export async function readSelectedChatAttachments(
  files: File[],
  existingFiles: AttachedFile[],
  notifyError: (message: string) => void,
): Promise<AttachedFile[]> {
  const selected: AttachedFile[] = [];
  const names = new Set(existingFiles.map((file) => file.name));

  for (const file of files) {
    if (existingFiles.length + selected.length >= MAX_ATTACHED_FILES) {
      notifyError(`添付できるファイルは${MAX_ATTACHED_FILES}件までです。`);
      break;
    }

    if (names.has(file.name)) continue;

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
      selected.push(attachment);
      names.add(file.name);
    } catch (error) {
      notifyError(`「${file.name}」を読み取れませんでした。`);
    }
  }

  return selected;
}
