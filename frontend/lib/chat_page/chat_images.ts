import type { AttachedFile, ChatAttachedImage, ChatHistoryAttachedImage } from "./types";

// 画像入力を受け付けるモデル。services/chat_images.py の IMAGE_INPUT_MODELS と揃える。
// Models that accept image input; keep in sync with IMAGE_INPUT_MODELS in services/chat_images.py.
const IMAGE_INPUT_MODELS: ReadonlySet<string> = new Set(["gpt-6-luna"]);

export const CHAT_IMAGE_ACCEPT = [".png", ".jpg", ".jpeg", ".webp", ".gif"].join(",");
const IMAGE_EXTENSION_PATTERN = /\.(png|jpe?g|webp|gif)$/i;

// 縮小前の元ファイルの上限。デコードに使うメモリを抑えるための値で、スマホの写真は収まる。
// Cap on the original file before downscaling; it bounds decode memory and fits phone photos.
export const MAX_CHAT_IMAGE_SOURCE_BYTES = 20 * 1024 * 1024;
// 縮小後の上限。services/chat_images.py の MAX_ATTACHED_IMAGE_BYTES と揃える。
// Cap after downscaling; keep in sync with MAX_ATTACHED_IMAGE_BYTES in services/chat_images.py.
export const MAX_CHAT_IMAGE_BYTES = 3 * 1024 * 1024;
const CHAT_IMAGE_MAX_DIMENSION = 2048;
const CHAT_IMAGE_QUALITY = 0.85;

export const IMAGE_INPUT_MODEL_ONLY_MESSAGE =
  "画像を読み込めるのは GPT-6 Luna だけです。モデルを GPT-6 Luna に切り替えるか、画像を外してください。";

export type DownscaledChatImage = {
  dataBase64: string;
  mediaType: string;
  size: number;
};

export function modelAcceptsImageInput(model: string): boolean {
  return IMAGE_INPUT_MODELS.has(model);
}

export function isImageAttachmentName(name: string): boolean {
  return IMAGE_EXTENSION_PATTERN.test(name);
}

export function hasImageAttachments(files: AttachedFile[]): boolean {
  return files.some((file) => isImageAttachmentName(file.name));
}

export function chatImageThumbnailUrl(imageId: string): string {
  return `/api/chat/images/${encodeURIComponent(imageId)}/thumbnail`;
}

// 送信直後の吹き出しは手元のプレビューで、履歴から開き直したときはサーバーのサムネイルで描く。
// A just-sent bubble draws the local preview; history reloaded from the server uses its thumbnail.
export function toBubbleImagesFromAttachments(files: AttachedFile[] | undefined): ChatAttachedImage[] | undefined {
  const images = (files ?? []).flatMap((file) => (file.previewUrl ? [{ name: file.name, src: file.previewUrl }] : []));
  return images.length > 0 ? images : undefined;
}

export function toBubbleImagesFromHistory(images: ChatHistoryAttachedImage[] | undefined): ChatAttachedImage[] | undefined {
  if (!images?.length) return undefined;
  return images.map((image) => ({
    name: image.name,
    src: chatImageThumbnailUrl(image.id),
    // 寸法が分からない画像は width/height を付けず、CSS の既定の大きさで描く。
    // Without known dimensions, omit width/height and let the CSS default size apply.
    width: image.width || undefined,
    height: image.height || undefined,
  }));
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("画像を変換できませんでした。"))), type, quality);
  });
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("画像を読み取れませんでした。"));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(blob);
  });
}

// 送る前に長辺を 2048px 以下へ縮め、WebP へ書き直す。書き直すと撮影位置などのメタデータも消える。
// Shrink the long side to at most 2048px and re-encode as WebP before sending; re-encoding also
// drops metadata such as the capture location.
export async function downscaleChatImage(file: File): Promise<DownscaledChatImage> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    const scale = Math.min(1, CHAT_IMAGE_MAX_DIMENSION / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("画像を変換できませんでした。");
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    let blob = await canvasToBlob(canvas, "image/webp", CHAT_IMAGE_QUALITY);
    // WebP を書き出せないブラウザは PNG を返すので、JPEG で縮め直す。透過部分は白で埋める。
    // Browsers that cannot encode WebP fall back to PNG, so re-encode as JPEG over a white fill.
    if (blob.type !== "image/webp") {
      context.globalCompositeOperation = "destination-over";
      context.fillStyle = "white";
      context.fillRect(0, 0, canvas.width, canvas.height);
      blob = await canvasToBlob(canvas, "image/jpeg", CHAT_IMAGE_QUALITY);
    }
    return { dataBase64: await blobToBase64(blob), mediaType: blob.type, size: blob.size };
  } finally {
    bitmap.close();
  }
}
