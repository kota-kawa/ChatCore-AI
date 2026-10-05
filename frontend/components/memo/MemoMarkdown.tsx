import { useEffect, useRef, type MouseEvent } from "react";

import { formatMemoOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

// ---------------------------------------------------------------------------
// MemoMarkdown component (renders LLM-formatted markdown)
// ---------------------------------------------------------------------------

// 指の当たり判定。チェック欄そのものは小さいので、同じ行の少し外側のタップも拾う
// Touch slop: the checkbox itself is small, so a tap just outside it on the same row counts too
const TASK_HIT_SLOP_PX = 12;

// index 番目のチェック欄を切り替える。描画されている欄の数も渡し、本文と食い違えば
// 呼び出し側が何もせず false を返せるようにする。
// Toggles the index-th checkbox. The number of rendered boxes is passed along so the caller can
// refuse (return false) when it does not match the source.
type ToggleTask = (index: number, renderedCount: number) => boolean;

function findTappedTask(container: HTMLElement, event: MouseEvent): HTMLInputElement | null {
  const target = event.target as HTMLElement;
  if (target instanceof HTMLInputElement && target.type === "checkbox") return target;
  if (target.closest("a, button")) return null;
  const item = target.closest("li");
  const box = item?.querySelector<HTMLInputElement>(":scope > input[type='checkbox'], :scope > p > input[type='checkbox']");
  if (!box || !container.contains(box)) return null;
  const rect = box.getBoundingClientRect();
  const inside =
    event.clientX >= rect.left - TASK_HIT_SLOP_PX && event.clientX <= rect.right + TASK_HIT_SLOP_PX &&
    event.clientY >= rect.top - TASK_HIT_SLOP_PX && event.clientY <= rect.bottom + TASK_HIT_SLOP_PX;
  return inside ? box : null;
}

// マークダウン形式のテキストをHTMLとしてレンダリングするコンポーネント。
// onToggleTask を渡すと、チェックリストの欄をその場で切り替えられる。
// Component to render markdown formatted text as HTML. With onToggleTask the checklist boxes can
// be ticked in place.
export function MemoMarkdown({ text, className, onToggleTask }: {
  text: string;
  className?: string;
  onToggleTask?: ToggleTask;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canToggleTasks = Boolean(onToggleTask);
  // Markdownのテキストが変更されたときにサニタイズして描画する副作用
  // Effect to render sanitized HTML when markdown text changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    renderSanitizedHTML(container, formatMemoOutput(text || ""));
    // メモから開いたリンクでメモ画面（編集中の内容）を離れないよう、別タブで開く
    // Links open in a new tab so following one never leaves the memo page (and what is being edited)
    container.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
    // Markdown の描画はチェック欄を無効化して出すので、切り替えられるときだけ有効に戻す
    // The Markdown renderer emits disabled checkboxes; enable them only when they can be toggled
    if (canToggleTasks) {
      container.querySelectorAll<HTMLInputElement>("input[type='checkbox']").forEach((box) => {
        box.disabled = false;
      });
    }
  }, [canToggleTasks, text]);

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container || !onToggleTask) return;
    const box = findTappedTask(container, event);
    if (!box) return;
    // ここで扱った合図。外側の「クリックで開く／編集する」は defaultPrevented を見て何もしない
    // Marks the click as handled; the outer "click to open / edit" handlers check defaultPrevented
    event.preventDefault();
    const boxes = Array.from(container.querySelectorAll<HTMLInputElement>("input[type='checkbox']"));
    const wasChecked = box === event.target ? !box.checked : box.checked;
    const toggled = onToggleTask(boxes.indexOf(box), boxes.length);
    // preventDefault はチェック欄自身のクリックだと見た目の切り替えも取り消すので、結果に合わせて置き直す
    // preventDefault also reverts the box's own visual toggle, so set it from the outcome
    const nextChecked = toggled ? !wasChecked : wasChecked;
    window.setTimeout(() => { box.checked = nextChecked; }, 0);
  };

  return <div ref={containerRef} className={className} onClick={onToggleTask ? handleClick : undefined}></div>;
}
