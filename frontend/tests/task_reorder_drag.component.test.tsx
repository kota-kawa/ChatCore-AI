import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { useTaskReorderDrag } from "../hooks/chat_page/use_task_reorder_drag";
import type { NormalizedTask } from "../lib/chat_page/types";

const TOUCH_HOLD_MS = 300;
const CARD_HEIGHT = 100;
const CONTAINER_HEIGHT = 600;

const makeTask = (taskId: number): NormalizedTask => ({
  task_id: taskId,
  name: `タスク${taskId}`,
  prompt_template: "",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
  is_default: false,
});

const tasks = [makeTask(1), makeTask(2), makeTask(3)];

type HarnessProps = {
  onDragStart: (dragIndex: number) => void;
  onDragEnd: (dragIndex: number, dropTargetIndex: number) => void;
};

// フックの挙動だけを検証するための最小構成のタスクリスト
// Minimal task list that exercises the hook without the rest of the setup screen
function ReorderHarness({ onDragStart, onDragEnd }: HarnessProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [draggingTaskIndex, setDraggingTaskIndex] = useState<number | null>(null);

  const { getTaskDomKey, setTaskWrapperRef, handleTaskPointerDown } = useTaskReorderDrag({
    tasks,
    isTaskOrderEditing: true,
    draggingTaskIndex,
    isDragInterrupted: false,
    onDragStart: (dragIndex) => {
      setDraggingTaskIndex(dragIndex);
      onDragStart(dragIndex);
    },
    onDragEnd: (dragIndex, dropTargetIndex) => {
      setDraggingTaskIndex(null);
      onDragEnd(dragIndex, dropTargetIndex);
    },
  });

  return (
    <div ref={containerRef} data-testid="scroll-container" style={{ overflowY: "auto" }}>
      {tasks.map((task, index) => {
        const taskDomKey = getTaskDomKey(task);
        return (
          <div
            key={taskDomKey}
            data-testid={`task-${index}`}
            className={`task-wrapper editable ${draggingTaskIndex === index ? "dragging" : ""}`.trim()}
            ref={(node) => {
              setTaskWrapperRef(taskDomKey, node);
            }}
            onPointerDown={(event) => {
              handleTaskPointerDown(event, index, taskDomKey);
            }}
          >
            {task.name}
          </div>
        );
      })}
    </div>
  );
}

function stubRect(element: HTMLElement, top: number, height: number) {
  element.getBoundingClientRect = () =>
    ({ top, bottom: top + height, left: 0, right: 320, width: 320, height, x: 0, y: top }) as DOMRect;
}

// jsdom はレイアウトしないため、カードとスクロールコンテナの寸法を手で与える
// jsdom performs no layout, so the card and container geometry has to be supplied by hand
function layoutHarness(scrollTopBox: { value: number }) {
  const container = screen.getByTestId("scroll-container");
  stubRect(container, 0, CONTAINER_HEIGHT);
  Object.defineProperty(container, "clientHeight", { value: CONTAINER_HEIGHT, configurable: true });
  Object.defineProperty(container, "scrollHeight", { value: 2000, configurable: true });
  Object.defineProperty(container, "scrollTop", {
    configurable: true,
    get: () => scrollTopBox.value,
    set: (next: number) => {
      scrollTopBox.value = next;
    },
  });

  tasks.forEach((_, index) => {
    stubRect(screen.getByTestId(`task-${index}`), index * CARD_HEIGHT, CARD_HEIGHT);
  });

  return container;
}

function pressCard(index: number, pointerType: "touch" | "mouse") {
  fireEvent.pointerDown(screen.getByTestId(`task-${index}`), {
    pointerId: 1,
    pointerType,
    button: 0,
    clientX: 160,
    clientY: index * CARD_HEIGHT + CARD_HEIGHT / 2,
  });
}

function movePointer(clientY: number, pointerType: "touch" | "mouse" = "touch") {
  fireEvent.pointerMove(window, { pointerId: 1, pointerType, clientX: 160, clientY });
}

describe("useTaskReorderDrag", () => {
  let onDragStart: Mock<(dragIndex: number) => void>;
  let onDragEnd: Mock<(dragIndex: number, dropTargetIndex: number) => void>;
  let scrollTopBox: { value: number };

  beforeEach(() => {
    vi.useFakeTimers();
    onDragStart = vi.fn<(dragIndex: number) => void>();
    onDragEnd = vi.fn<(dragIndex: number, dropTargetIndex: number) => void>();
    scrollTopBox = { value: 0 };
    render(<ReorderHarness onDragStart={onDragStart} onDragEnd={onDragEnd} />);
    layoutHarness(scrollTopBox);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // 縦スワイプでカードを掴んでしまうと、スマホでは一覧をスクロールできなくなる
  // Grabbing a card on a plain swipe is what made the list impossible to scroll on phones
  it("lets a swipe scroll instead of reordering when the finger moves before the hold completes", () => {
    pressCard(0, "touch");
    act(() => {
      vi.advanceTimersByTime(80);
    });
    movePointer(30);

    act(() => {
      vi.advanceTimersByTime(TOUCH_HOLD_MS);
    });

    expect(onDragStart).not.toHaveBeenCalled();
    expect(onDragEnd).not.toHaveBeenCalled();

    // 候補が破棄された後の指の動きでもカードは動かない
    // Once the candidate is dropped, further movement must not move the card either
    movePointer(400);
    expect(screen.getByTestId("task-0").style.transform).toBe("");
  });

  it("keeps browser scrolling available until the card is picked up", () => {
    pressCard(0, "touch");

    const scrolledFreely = fireEvent.touchMove(document, { cancelable: true, bubbles: true });
    expect(scrolledFreely).toBe(true);
  });

  it("picks the card up after a still hold and reorders on release", () => {
    pressCard(0, "touch");
    act(() => {
      vi.advanceTimersByTime(TOUCH_HOLD_MS);
    });

    expect(onDragStart).toHaveBeenCalledWith(0);

    // 掴んだ後はブラウザのスクロールを止めて、指の動きを並び替えに使う
    // After the pick-up the browser must stop scrolling so the finger drives the drag
    const blockedScroll = fireEvent.touchMove(document, { cancelable: true, bubbles: true });
    expect(blockedScroll).toBe(false);

    movePointer(250);
    expect(screen.getByTestId("task-0").style.transform).toContain("translate3d");

    fireEvent.pointerUp(window, { pointerId: 1, pointerType: "touch", clientX: 160, clientY: 250 });
    expect(onDragEnd).toHaveBeenCalledWith(0, 2);
  });

  it("cancels a pending hold when the list scrolls under the finger", () => {
    pressCard(0, "touch");
    fireEvent.scroll(screen.getByTestId("scroll-container"));

    act(() => {
      vi.advanceTimersByTime(TOUCH_HOLD_MS);
    });

    expect(onDragStart).not.toHaveBeenCalled();
  });

  it("scrolls the list automatically while a dragged card sits near the bottom edge", () => {
    pressCard(0, "touch");
    act(() => {
      vi.advanceTimersByTime(TOUCH_HOLD_MS);
    });

    movePointer(CONTAINER_HEIGHT - 10);
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(scrollTopBox.value).toBeGreaterThan(0);

    // ドロップすると自動スクロールも止まる
    // Dropping the card also stops the auto-scroll loop
    fireEvent.pointerUp(window, { pointerId: 1, pointerType: "touch", clientX: 160, clientY: CONTAINER_HEIGHT - 10 });
    const scrollTopAfterDrop = scrollTopBox.value;
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(scrollTopBox.value).toBe(scrollTopAfterDrop);
  });

  it("still starts a mouse drag from the movement threshold alone", () => {
    pressCard(0, "mouse");
    movePointer(30, "mouse");

    expect(onDragStart).toHaveBeenCalledWith(0);
  });

  it("ignores a second finger while a card is being dragged", () => {
    pressCard(0, "touch");
    act(() => {
      vi.advanceTimersByTime(TOUCH_HOLD_MS);
    });
    expect(onDragStart).toHaveBeenCalledTimes(1);

    fireEvent.pointerDown(screen.getByTestId("task-2"), {
      pointerId: 2,
      pointerType: "touch",
      button: 0,
      clientX: 160,
      clientY: 250,
    });

    expect(onDragEnd).not.toHaveBeenCalled();

    movePointer(250);
    fireEvent.pointerUp(window, { pointerId: 1, pointerType: "touch", clientX: 160, clientY: 250 });
    expect(onDragEnd).toHaveBeenCalledWith(0, 2);
  });
});
