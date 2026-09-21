import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TaskCard, type TaskCardProps } from "../components/chat_page/setup_section";
import type { NormalizedTask } from "../lib/chat_page/types";

const task: NormalizedTask = {
  task_id: 1,
  name: "要約する",
  prompt_template: "次の文章を要約してください。",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
  is_default: false
};

function renderTaskCard(overrides: Partial<TaskCardProps> = {}) {
  const onLaunch = vi.fn();
  const onDelete = vi.fn();
  const onEdit = vi.fn();
  const onShowDetail = vi.fn();
  const onTaskPointerDown = vi.fn();
  const onFinishPointerDrag = vi.fn();
  const setTaskWrapperRef = vi.fn();
  const { container } = render(
    <TaskCard
      task={task}
      index={0}
      taskDomKey="task-1"
      isEditing={false}
      isDragging={false}
      isLaunching={false}
      setTaskWrapperRef={setTaskWrapperRef}
      onTaskPointerDown={onTaskPointerDown}
      onFinishPointerDrag={onFinishPointerDrag}
      onLaunch={onLaunch}
      onDelete={onDelete}
      onEdit={onEdit}
      onShowDetail={onShowDetail}
      {...overrides}
    />,
  );
  return { container, onLaunch };
}

// ホーム画面のタスクカードはクリックでしか起動できなかった。role/tabIndex/onKeyDownを
// 固定して、キーボードのみでもタスクを起動できることを保証する。
// The home screen's task card used to launch only on click. Lock in role/tabIndex/onKeyDown
// so keyboard-only users can launch a task too.
describe("SetupSection task card keyboard access", () => {
  it("exposes role=button and tabIndex=0, and launches on Enter/Space", () => {
    const { container, onLaunch } = renderTaskCard();
    const card = container.querySelector<HTMLDivElement>(".prompt-card");

    expect(card?.getAttribute("role")).toBe("button");
    expect(card?.getAttribute("tabindex")).toBe("0");

    card?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));
    expect(onLaunch).toHaveBeenCalledTimes(1);
    expect(onLaunch).toHaveBeenCalledWith(task);

    card?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: " " }));
    expect(onLaunch).toHaveBeenCalledTimes(2);
  });

  it("ignores key events bubbling from the detail toggle button", () => {
    const { container, onLaunch } = renderTaskCard();
    const detailToggle = container.querySelector<HTMLButtonElement>(".task-detail-toggle");

    detailToggle?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));

    expect(onLaunch).not.toHaveBeenCalled();
  });

  it("does not launch on Enter/Space while in edit/reorder mode", () => {
    const { container, onLaunch } = renderTaskCard({ isEditing: true });
    const card = container.querySelector<HTMLDivElement>(".prompt-card");

    expect(card?.getAttribute("aria-disabled")).toBe("true");
    card?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));

    expect(onLaunch).not.toHaveBeenCalled();
  });
});
