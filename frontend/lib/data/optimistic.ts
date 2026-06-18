// 楽観的更新の共通ヘルパー。UI を即座に更新し、サーバー反映の失敗時に自動で巻き戻す。
// A shared optimistic-mutation helper: update the UI instantly and roll back automatically
// when the server request fails.
//
// SWR の mutate が持つ optimisticData / rollbackOnError を土台に、失敗時のトースト通知と
// 成功後の再検証ポリシーを一箇所に集約する。これにより遅い回線でも操作が即時に感じられる。
// Built on SWR mutate's optimisticData / rollbackOnError, this centralizes failure toasts and
// the post-success revalidation policy so actions feel instant even on slow networks.

import type { KeyedMutator } from "swr";
import { showToast } from "../../scripts/core/toast";

export type OptimisticMutationConfig<Data, Result> = {
  // 対象 SWR キーのバインド済み mutate（useSWR が返す mutate）。
  // The bound mutate for the target SWR key (returned by useSWR).
  mutate: KeyedMutator<Data>;
  // 楽観的に表示する次の状態（現在値から算出）。
  // The next state to show optimistically (derived from the current value).
  optimisticData: Data | ((current: Data | undefined) => Data);
  // 実際のサーバーリクエスト。解決値はそのまま呼び出し元に返す。
  // The actual server request; its resolved value is returned to the caller.
  request: () => Promise<Result>;
  // 成功時に再検証するか（既定: true）。一覧の整合性を取りたい場合に有効。
  // Whether to revalidate on success (default: true) to reconcile with the server.
  revalidate?: boolean;
  // 失敗時に表示するメッセージ（未指定ならトーストを出さない）。
  // Message shown on failure (no toast when omitted).
  rollbackMessage?: string;
  // 成功時に表示するメッセージ（任意）。
  // Optional message shown on success.
  successMessage?: string;
};

/**
 * 楽観的更新を実行する。失敗時は SWR が自動的に元データへ巻き戻し、トーストで通知する。
 * Run an optimistic mutation. On failure SWR rolls back to the previous data and we toast.
 *
 * @returns サーバーリクエストの解決値。失敗時は例外を再スローする。
 *          The resolved value of the server request; rethrows on failure.
 */
export async function runOptimisticMutation<Data, Result>(
  config: OptimisticMutationConfig<Data, Result>,
): Promise<Result> {
  const { mutate, optimisticData, request, revalidate = true, rollbackMessage, successMessage } = config;

  let result!: Result;
  try {
    await mutate(
      async (current) => {
        result = await request();
        return current as Data;
      },
      {
        optimisticData: optimisticData as Data | ((current: Data | undefined) => Data),
        rollbackOnError: true,
        revalidate,
        // request 側で結果を取得済みのため、ここでは現在のキャッシュ構造を保つ。
        // The result is captured in `request`; keep the existing cache shape here.
        populateCache: false,
      },
    );
    if (successMessage) showToast(successMessage, { variant: "success" });
    return result;
  } catch (error) {
    if (rollbackMessage) showToast(rollbackMessage, { variant: "error" });
    throw error;
  }
}
