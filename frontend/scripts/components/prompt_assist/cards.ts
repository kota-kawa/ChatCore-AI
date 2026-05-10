// AI提案の各フィールドを、プレビュー内に1行ずつ表示するための軽量カード
// Lightweight row used to render one suggested field inside the preview.
export function createSuggestionRow(label: string, value: string, isPrimary: boolean) {
  const row = document.createElement("div");
  row.className = "prompt-assist__row";
  if (isPrimary) {
    row.classList.add("prompt-assist__row--primary");
  }

  const head = document.createElement("span");
  head.className = "prompt-assist__row-label";
  head.textContent = label;

  const body = document.createElement("p");
  body.className = "prompt-assist__row-value";
  body.textContent = value;

  row.append(head, body);
  return row;
}
