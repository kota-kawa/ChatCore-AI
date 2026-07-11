export type StopGenerationRequest = (roomId: string) => Promise<unknown>;

// サーバー側の生成ロックが解除されるまで、クライアント側の生成ガードを保持する。
// Keep the client-side generation guard until the server has released its generation lock.
export async function stopGenerationBeforeDisconnect(
  roomId: string,
  requestStop: StopGenerationRequest,
  disconnect: () => void,
): Promise<void> {
  try {
    await requestStop(roomId);
  } finally {
    disconnect();
  }
}
