// 生成の停止要求をサーバーへ送り、その完了後に SSE 接続を切るための小さな手順。
// Small routine that sends the stop request to the server and only then drops the SSE connection.
// Used by hooks/chat_page/use_home_page_generation_actions.ts.

// ルームの生成停止をサーバーへ要求する関数の型。
// Function type that asks the server to stop generation for a room.

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
