import type { MutableRefObject } from "react";

export function nextMessageId(prefix: string, seqRef: MutableRefObject<number>) {
  seqRef.current += 1;
  return `${prefix}-${Date.now()}-${seqRef.current}`;
}
