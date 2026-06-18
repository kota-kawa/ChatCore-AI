import assert from "node:assert/strict";
import test from "node:test";

import { runOptimisticMutation } from "../lib/data/optimistic";

// SWR の mutate の最小モック。関数アップデーターを実行し、その解決/拒否を伝播する。
// Minimal mock of SWR's mutate: runs the function updater and propagates resolve/reject.
function fakeMutate<Data>() {
  return (async (updater: unknown) => {
    if (typeof updater === "function") {
      return await (updater as (current: Data | undefined) => Promise<Data>)(undefined);
    }
    return updater as Data;
  }) as never;
}

test("returns the request result on success", async () => {
  let requested = false;
  const result = await runOptimisticMutation<{ liked: boolean }, string>({
    mutate: fakeMutate<{ liked: boolean }>(),
    optimisticData: { liked: true },
    request: async () => {
      requested = true;
      return "ok";
    },
  });
  assert.equal(result, "ok");
  assert.equal(requested, true);
});

test("rethrows when the request fails (so SWR can roll back)", async () => {
  await assert.rejects(
    () =>
      runOptimisticMutation<{ liked: boolean }, string>({
        mutate: fakeMutate<{ liked: boolean }>(),
        optimisticData: { liked: true },
        request: async () => {
          throw new Error("network down");
        },
        rollbackMessage: "失敗しました",
      }),
    /network down/,
  );
});
