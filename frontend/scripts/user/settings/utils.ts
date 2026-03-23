export function truncateTitle(title: string) {
  const chars = Array.from(title);
  return chars.length > 17 ? chars.slice(0, 17).join("") + "..." : title;
}

export function escapeHtml(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
