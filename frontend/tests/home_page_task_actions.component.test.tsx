import { act, renderHook, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageTaskActions } from "../hooks/chat_page/use_home_page_task_actions";
import { useHomePageTaskState } from "../hooks/chat_page/use_home_page_task_state";
import type { NormalizedTask, TaskEditFormState } from "../lib/chat_page/types";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";

vi.mock("../scripts/core/alert_modal", () => ({
  showConfirmModal: vi.fn(),
}));
vi.mock("../scripts/core/toast", () => ({
  showToast: vi.fn(),
}));
vi.mock("../scripts/core/runtime_validation", () => ({
  fetchJsonOrThrow: vi.fn(),
}));

const makeTask = (taskId: number, promptTemplate: string): NormalizedTask => ({
  task_id: taskId,
  name: "同名タスク",
  prompt_template: promptTemplate,
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
  is_default: false,
});

const emptyEditForm: TaskEditFormState = {
  task_id: null,
  new_task: "",
  prompt_template: "",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
};

function useTaskActionsHarness(initialTasks: NormalizedTask[]) {
  const [tasks, setTasks] = useState(initialTasks);
  const [isTaskOrderEditing, setIsTaskOrderEditing] = useState(false);
  const [, setTasksExpanded] = useState(false);
  const [, setDraggingTaskIndex] = useState<number | null>(null);
  const [taskEditForm, setTaskEditForm] = useState(emptyEditForm);
  const [, setTaskEditModalOpen] = useState(false);
  const draggingTaskIndexRef = useRef<number | null>(null);

  const actions = useHomePageTaskActions({
    loggedIn: true,
    tasks,
    setTasks,
    isTaskOrderEditing,
    setIsTaskOrderEditing,
    setTasksExpanded,
    setDraggingTaskIndex,
    draggingTaskIndexRef,
    taskEditForm,
    setTaskEditForm,
    setTaskEditModalOpen,
  });

  return { tasks, setTaskEditForm, ...actions };
}

describe("useHomePageTaskActions", () => {
  beforeEach(() => {
    vi.mocked(showConfirmModal).mockResolvedValue(true);
    vi.mocked(fetchJsonOrThrow).mockResolvedValue({ payload: {} } as never);
  });

  it("deletes only the selected task id when names are duplicated", async () => {
    const { result } = renderHook(() => useTaskActionsHarness([
      makeTask(10, "first"),
      makeTask(11, "second"),
    ]));

    await act(async () => {
      await result.current.handleTaskDelete(10);
    });

    expect(result.current.tasks.map((task) => task.task_id)).toEqual([11]);
    expect(fetchJsonOrThrow).toHaveBeenCalledWith(
      "/api/delete_task",
      expect.objectContaining({ body: JSON.stringify({ task_id: 10 }) }),
      expect.any(Object),
    );
  });

  it("ignores an older task refresh that finishes after a newer one", async () => {
    let resolveFirst: ((value: unknown) => void) | undefined;
    let resolveSecond: ((value: unknown) => void) | undefined;
    vi.mocked(fetchJsonOrThrow)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }) as never)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }) as never);

    const { result } = renderHook(() => useTaskActionsHarness([]));
    let firstRefresh: Promise<void>;
    let secondRefresh: Promise<void>;
    act(() => {
      firstRefresh = result.current.refreshTasks(true);
      secondRefresh = result.current.refreshTasks(true);
    });

    await act(async () => {
      resolveSecond?.({ payload: { tasks: [{ task_id: 22, name: "new" }] } });
      await secondRefresh!;
    });
    await waitFor(() => expect(result.current.tasks[0]?.task_id).toBe(22));

    await act(async () => {
      resolveFirst?.({ payload: { tasks: [{ task_id: 21, name: "old" }] } });
      await firstRefresh!;
    });
    expect(result.current.tasks[0]?.task_id).toBe(22);
  });
});

describe("useHomePageTaskState", () => {
  it("starts empty so authenticated users never see editable fallback cards", () => {
    const { result } = renderHook(() => useHomePageTaskState());
    expect(result.current.tasks).toEqual([]);
  });
});
