import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import {
  buildTaskOrderForPersistence,
} from "../../lib/chat_page/home_page_controller_utils";
import { FALLBACK_TASKS, normalizeTaskList } from "../../lib/chat_page/task_utils";
import type { NormalizedTask, TaskEditFormState } from "../../lib/chat_page/types";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import { fetchJsonOrThrow } from "../../scripts/core/runtime_validation";
import type { TaskItem } from "../../scripts/setup/setup_types";
import {
  invalidateTasksCache,
  readCachedTasks,
  writeCachedTasks,
} from "../../scripts/setup/setup_tasks_cache";

type UseHomePageTaskActionsParams = {
  tasks: NormalizedTask[];
  setTasks: Dispatch<SetStateAction<NormalizedTask[]>>;
  isTaskOrderEditing: boolean;
  setIsTaskOrderEditing: Dispatch<SetStateAction<boolean>>;
  setTasksExpanded: Dispatch<SetStateAction<boolean>>;
  setDraggingTaskIndex: Dispatch<SetStateAction<number | null>>;
  draggingTaskIndexRef: MutableRefObject<number | null>;
  taskEditForm: TaskEditFormState;
  setTaskEditForm: Dispatch<SetStateAction<TaskEditFormState>>;
  setTaskEditModalOpen: Dispatch<SetStateAction<boolean>>;
};

export function useHomePageTaskActions({
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
}: UseHomePageTaskActionsParams) {
  const refreshTasks = useCallback(
    async (forceRefresh = false) => {
      if (!forceRefresh) {
        const cached = readCachedTasks();
        if (Array.isArray(cached) && cached.length > 0) {
          setTasks(normalizeTaskList(cached));
          return;
        }
      }

      setTasks(FALLBACK_TASKS);

      try {
        const { payload } = await fetchJsonOrThrow<{ tasks?: TaskItem[] }>("/api/tasks", undefined, {
          defaultMessage: "タスクの読み込みに失敗しました。",
        });

        const fetchedTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
        if (fetchedTasks.length > 0) {
          writeCachedTasks(fetchedTasks);
        }

        setTasks(normalizeTaskList(fetchedTasks));
      } catch (error) {
        console.error("タスク読み込みに失敗:", error);
        setTasks(FALLBACK_TASKS);
      }
    },
    [],
  );

  const saveTaskOrder = useCallback(async (nextTasks: NormalizedTask[]) => {
    const order = buildTaskOrderForPersistence(nextTasks);

    if (order.length === 0) return;

    try {
      await fetchJsonOrThrow("/api/update_tasks_order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ order }),
      });
      invalidateTasksCache();
    } catch (error) {
      const message = error instanceof Error ? error.message : "並び順の保存に失敗しました。";
      showToast(`並び順の保存に失敗: ${message}`, { variant: "error" });
    }
  }, []);

  const toggleTaskOrderEditing = useCallback(() => {
    setIsTaskOrderEditing((previous) => {
      const next = !previous;
      if (next) {
        setTasksExpanded(true);
      } else {
        draggingTaskIndexRef.current = null;
        setDraggingTaskIndex(null);
        setTasksExpanded(false);
        void saveTaskOrder(tasks);
      }
      return next;
    });
  }, [saveTaskOrder, tasks]);

  const handleTaskDragStart = useCallback(
    (index: number) => {
      if (!isTaskOrderEditing) return;
      draggingTaskIndexRef.current = index;
      setDraggingTaskIndex(index);
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragEnd = useCallback((dragIndex: number, dropTargetIndex: number) => {
    draggingTaskIndexRef.current = null;
    setDraggingTaskIndex(null);

    if (dragIndex === dropTargetIndex) return;

    setTasks((previous) => {
      if (dragIndex < 0 || dragIndex >= previous.length) return previous;
      if (dropTargetIndex < 0 || dropTargetIndex >= previous.length) return previous;
      const next = [...previous];
      const [moved] = next.splice(dragIndex, 1);
      if (!moved) return previous;
      next.splice(dropTargetIndex, 0, moved);
      return next;
    });
  }, []);

  const handleTaskDelete = useCallback(
    async (taskName: string) => {
      const confirmed = await showConfirmModal("このタスクを削除してもよろしいですか？");
      if (!confirmed) return;

      try {
        await fetchJsonOrThrow("/api/delete_task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ task: taskName }),
        });

        setTasks((previous) => {
          const next = previous.filter((task) => task.name !== taskName);
          void saveTaskOrder(next);
          return next;
        });
        invalidateTasksCache();
      } catch (error) {
        showToast(`削除に失敗しました: ${error instanceof Error ? error.message : String(error)}`, {
          variant: "error",
        });
      }
    },
    [saveTaskOrder],
  );

  const openTaskEditModal = useCallback((task: NormalizedTask) => {
    setTaskEditForm({
      old_task: task.name,
      new_task: task.name,
      prompt_template: task.prompt_template,
      response_rules: task.response_rules,
      output_skeleton: task.output_skeleton,
      input_examples: task.input_examples,
      output_examples: task.output_examples,
    });
    setTaskEditModalOpen(true);
  }, []);

  const closeTaskEditModal = useCallback(() => {
    setTaskEditModalOpen(false);
  }, []);

  const handleTaskEditSave = useCallback(async () => {
    const payload = {
      old_task: taskEditForm.old_task,
      new_task: taskEditForm.new_task.trim(),
      prompt_template: taskEditForm.prompt_template,
      response_rules: taskEditForm.response_rules,
      output_skeleton: taskEditForm.output_skeleton,
      input_examples: taskEditForm.input_examples,
      output_examples: taskEditForm.output_examples,
    };

    if (!payload.new_task) {
      showToast("タイトルを入力してください。", { variant: "error" });
      return;
    }

    try {
      await fetchJsonOrThrow("/api/edit_task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });

      setTasks((previous) =>
        previous.map((task) => {
          if (task.name !== taskEditForm.old_task) return task;
          return {
            ...task,
            name: payload.new_task,
            prompt_template: payload.prompt_template,
            response_rules: payload.response_rules,
            output_skeleton: payload.output_skeleton,
            input_examples: payload.input_examples,
            output_examples: payload.output_examples,
          };
        }),
      );
      invalidateTasksCache();
      closeTaskEditModal();
    } catch (error) {
      showToast(`更新に失敗しました: ${error instanceof Error ? error.message : String(error)}`, {
        variant: "error",
      });
    }
  }, [closeTaskEditModal, taskEditForm]);

  return {
    refreshTasks,
    saveTaskOrder,
    toggleTaskOrderEditing,
    handleTaskDragStart,
    handleTaskDragEnd,
    handleTaskDelete,
    openTaskEditModal,
    closeTaskEditModal,
    handleTaskEditSave,
  };
}
