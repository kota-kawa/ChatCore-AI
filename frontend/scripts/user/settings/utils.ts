export { escapeHtml } from "../../core/html";

export function truncateTitle(title: string) {
  const chars = Array.from(title);
  return chars.length > 17 ? chars.slice(0, 17).join("") + "..." : title;
}
