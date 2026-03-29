/**
 * 確認ダイアログ付き API 操作の共通パターン
 */
import { showConfirmModal } from "./alert_modal";
import { fetchJsonOrThrow } from "./runtime_validation";

type ConfirmAndDeleteOptions = {
  /** 確認ダイアログに表示するメッセージ */
  message: string;
  /** DELETE リクエスト先 URL */
  url: string;
  /** 追加の RequestInit（credentials など） */
  init?: RequestInit;
  /** 成功時のデフォルトメッセージ */
  successMessage?: string;
  /** エラー時のデフォルトメッセージ */
  errorMessage?: string;
  /** 成功後のコールバック */
  onSuccess: () => void;
};

export async function confirmAndDelete(options: ConfirmAndDeleteOptions): Promise<void> {
  const confirmed = await showConfirmModal(options.message);
  if (!confirmed) return;

  try {
    const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
      options.url,
      { method: "DELETE", ...options.init },
      {
        defaultMessage: options.errorMessage || "削除に失敗しました。"
      }
    );
    alert(
      typeof payload.message === "string" && payload.message.trim()
        ? payload.message
        : (options.successMessage || "削除しました。")
    );
    options.onSuccess();
  } catch (err) {
    console.error("削除中のエラー:", err);
    alert(err instanceof Error ? err.message : (options.errorMessage || "削除に失敗しました。"));
  }
}
