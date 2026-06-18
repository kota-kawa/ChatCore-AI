// 読み込み中のプレースホルダーを表示する再利用可能なスケルトンコンポーネント。
// A reusable skeleton placeholder shown while content is loading.
//
// 空白やスピナーの代わりに「コンテンツの形」を先に見せることで、遅い回線でも待ち時間の体感を下げる。
// Showing the shape of content (instead of a blank or spinner) reduces perceived latency on slow links.
// 見た目は globals.css の .cc-skeleton トークンに従い、prefers-reduced-motion でシマーは止まる。
// Visuals follow the .cc-skeleton tokens in globals.css; the shimmer halts under prefers-reduced-motion.

import type { CSSProperties } from "react";

function joinClasses(...classes: Array<string | undefined | false>): string {
  return classes.filter(Boolean).join(" ");
}

export type SkeletonProps = {
  // 角丸の形状。テキスト行・矩形ブロック・円形（アバター等）。
  // Corner shape: text line, rectangular block, or circle (e.g. avatars).
  variant?: "text" | "block" | "circle";
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: CSSProperties;
};

// 単一のスケルトン要素。
// A single skeleton element.
export function Skeleton({ variant = "block", width, height, className, style }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      className={joinClasses("cc-skeleton", `cc-skeleton--${variant}`, className)}
      style={{ width, height, ...style }}
    />
  );
}

export type SkeletonTextProps = {
  // 行数。最後の行は短めにして自然な段落に見せる。
  // Number of lines; the last line is shortened to look like a natural paragraph.
  lines?: number;
  className?: string;
};

// 複数行のテキストスケルトン。
// A multi-line text skeleton.
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <span className={joinClasses("cc-skeleton-text", className)} aria-hidden="true">
      {Array.from({ length: Math.max(1, lines) }).map((_, index) => (
        <Skeleton
          key={index}
          variant="text"
          width={index === lines - 1 ? "62%" : "100%"}
        />
      ))}
    </span>
  );
}
