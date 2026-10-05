// ---------------------------------------------------------------------------
// Memo titles derived from the body
// ---------------------------------------------------------------------------

// タイトルを付けずに保存したメモは、サーバーが本文の最初の行をタイトルにする
// （services/repositories/memo_helpers.py の ensure_title と同じ規則）。
// A memo saved without a title gets the first line of its body as the title on the server
// (the same rule as ensure_title in services/repositories/memo_helpers.py).
export function autoMemoTitle(body: string): string {
  for (const line of body.split(/\r?\n/)) {
    const cleaned = line.trim();
    if (cleaned) return cleaned.slice(0, 255);
  }
  return "";
}

// タイトルが本文から自動で付いたもの（＝利用者が付けた題ではない）か
// Whether the title is the one derived from the body (that is, not one the user wrote)
export function isAutoMemoTitle(title: string | null | undefined, body: string): boolean {
  return Boolean(title) && title === autoMemoTitle(body);
}
