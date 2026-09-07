// SSE のバイト列を「空行区切りのイベントブロック」へ組み立てるだけの境界。
// TextDecoder は再接続をまたいで使い回すため呼び出し側が保持し、行バッファは
// レスポンス1本ごとに作り直す（前の接続の途中行を次の接続へ持ち込まない）。
// Boundary that only assembles SSE bytes into blank-line separated event
// blocks. The TextDecoder is owned by the caller so it can be reused across
// reconnects, while the line buffer is recreated per response so a partial
// line from a dropped connection never leaks into the next one.

export type SseTextDecoder = Pick<TextDecoder, "decode">;

export type SseBlockDecoder = {
  // 受信チャンクを取り込み、完成したイベントブロックだけを返す。
  // Feed a received chunk and return only the completed event blocks.
  push: (value: Uint8Array | undefined, done: boolean) => string[];
  // まだブロックとして閉じていない残りの行バッファ。
  // The trailing buffer that has not been closed into a block yet.
  readonly pending: string;
};

const SSE_BLOCK_SEPARATOR = /\r?\n\r?\n/;

export function createSseBlockDecoder(textDecoder: SseTextDecoder = new TextDecoder()): SseBlockDecoder {
  let buffer = "";

  return {
    push(value: Uint8Array | undefined, done: boolean) {
      buffer += textDecoder.decode(value || new Uint8Array(), { stream: !done });

      const blocks = buffer.split(SSE_BLOCK_SEPARATOR);
      buffer = blocks.pop() || "";
      return blocks;
    },
    get pending() {
      return buffer;
    },
  };
}
