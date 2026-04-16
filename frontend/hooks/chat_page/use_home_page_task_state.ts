import { useMemo, useRef, useState } from "react";

import { FALLBACK_TASKS } from "../../lib/chat_page/task_utils";
import type { NormalizedTask, TaskEditFormState } from "../../lib/chat_page/types";

const EMPTY_TASK_EDIT_FORM: TaskEditFormState = {
  old_task: "",
  new_task: "",
  prompt_template: "",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
};

export function useHomePageTaskState() {
  const [tasks, setTasks] = useState<NormalizedTask[]>(FALLBACK_TASKS);
  const [tasksExpanded, setTasksExpanded] = useState(false);
  const [isTaskOrderEditing, setIsTaskOrderEditing] = useState(false);
  const [taskDetail, setTaskDetail] = useState<NormalizedTask | null>(null);
  const [launchingTaskName, setLaunchingTaskName] = useState<string | null>(null);
  const [draggingTaskIndex, setDraggingTaskIndex] = useState<number | null>(null);
  const taskLaunchInProgressRef = useRef(false);

  const [taskEditModalOpen, setTaskEditModalOpen] = useState(false);
  const [taskEditForm, setTaskEditForm] = useState<TaskEditFormState>(EMPTY_TASK_EDIT_FORM);

  const showTaskToggleButton = useMemo(() => {
    return tasks.length > 6 && !isTaskOrderEditing;
  }, [isTaskOrderEditing, tasks.length]);

  const visibleTaskCountText = useMemo(() => {
    return tasksExpanded || isTaskOrderEditing ? "閉じる" : "もっと見る";
  }, [isTaskOrderEditing, tasksExpanded]);

  return {
    tasks,
    setTasks,
    tasksExpanded,
    setTasksExpanded,
    isTaskOrderEditing,
    setIsTaskOrderEditing,
    taskDetail,
    setTaskDetail,
    launchingTaskName,
    setLaunchingTaskName,
    draggingTaskIndex,
    setDraggingTaskIndex,
    taskLaunchInProgressRef,
    taskEditModalOpen,
    setTaskEditModalOpen,
    taskEditForm,
    setTaskEditForm,
    showTaskToggleButton,
    visibleTaskCountText,
  };
}
