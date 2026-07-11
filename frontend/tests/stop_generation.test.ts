import assert from "node:assert/strict";
import test from "node:test";

import { stopGenerationBeforeDisconnect } from "../lib/chat_page/stop_generation";

test("keeps the client generation guard until the stop request finishes", async () => {
  let resolveStop: (() => void) | undefined;
  let disconnected = false;
  const stopRequest = new Promise<void>((resolve) => {
    resolveStop = resolve;
  });

  const stopping = stopGenerationBeforeDisconnect(
    "room-a",
    () => stopRequest,
    () => {
      disconnected = true;
    },
  );

  await Promise.resolve();
  assert.equal(disconnected, false);

  resolveStop?.();
  await stopping;
  assert.equal(disconnected, true);
});

test("releases the client generation guard when the stop request fails", async () => {
  let disconnected = false;

  await assert.rejects(
    stopGenerationBeforeDisconnect(
      "room-a",
      async () => {
        throw new Error("network failure");
      },
      () => {
        disconnected = true;
      },
    ),
    /network failure/,
  );

  assert.equal(disconnected, true);
});
