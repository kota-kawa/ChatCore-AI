// Markdown記法を取り除き、カードやOGP向けの読みやすいプレーンテキストに変換する
// Strips Markdown syntax to produce a clean plain-text preview for cards and OGP descriptions
export function stripMarkdownForPreview(value: string): string {
  return (value || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
