import { useEffect, useMemo, useRef, useState } from "react";

import type { NormalizedTask, TaskEditFormState } from "../../lib/chat_page/types";
import { useTranslation } from "../../contexts/locale_context";

const EMPTY_TASK_EDIT_FORM: TaskEditFormState = {
  task_id: null,
  new_task: "",
  prompt_template: "",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
};

const DESKTOP_TASK_COLLAPSE_LIMIT = 6;
const MOBILE_TASK_COLLAPSE_LIMIT = 4;
const MOBILE_TASK_COLLAPSE_QUERY = "(max-width: 576px)";

export function useHomePageTaskState() {
  const { locale } = useTranslation();
  const [tasks, setTasks] = useState<NormalizedTask[]>([]);
  const [tasksExpanded, setTasksExpanded] = useState(false);
  const [isTaskOrderEditing, setIsTaskOrderEditing] = useState(false);
  const [taskDetail, setTaskDetail] = useState<NormalizedTask | null>(null);
  const [launchingTaskName, setLaunchingTaskName] = useState<string | null>(null);
  const [launchingTaskId, setLaunchingTaskId] = useState<number | null>(null);
  const [draggingTaskIndex, setDraggingTaskIndex] = useState<number | null>(null);
  const [taskCollapseLimit, setTaskCollapseLimit] = useState(DESKTOP_TASK_COLLAPSE_LIMIT);
  const taskLaunchInProgressRef = useRef(false);

  const [taskEditModalOpen, setTaskEditModalOpen] = useState(false);
  const [taskEditForm, setTaskEditForm] = useState<TaskEditFormState>(EMPTY_TASK_EDIT_FORM);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;

    const mediaQuery = window.matchMedia(MOBILE_TASK_COLLAPSE_QUERY);
    const updateTaskCollapseLimit = () => {
      setTaskCollapseLimit(mediaQuery.matches ? MOBILE_TASK_COLLAPSE_LIMIT : DESKTOP_TASK_COLLAPSE_LIMIT);
    };

    updateTaskCollapseLimit();
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", updateTaskCollapseLimit);

      return () => {
        mediaQuery.removeEventListener("change", updateTaskCollapseLimit);
      };
    }

    mediaQuery.addListener(updateTaskCollapseLimit);

    return () => {
      mediaQuery.removeListener(updateTaskCollapseLimit);
    };
  }, []);

  const showTaskToggleButton = useMemo(() => {
    return tasks.length > taskCollapseLimit && !isTaskOrderEditing;
  }, [isTaskOrderEditing, taskCollapseLimit, tasks.length]);

  const visibleTaskCountText = useMemo(() => {
    return locale === "en" ? (tasksExpanded || isTaskOrderEditing ? "Show less" : "Show more") : (tasksExpanded || isTaskOrderEditing ? "閉じる" : "もっと見る");
  }, [isTaskOrderEditing, locale, tasksExpanded]);

  return {
    tasks,
    setTasks,
    tasksExpanded,
    setTasksExpanded,
    taskCollapseLimit,
    isTaskOrderEditing,
    setIsTaskOrderEditing,
    taskDetail,
    setTaskDetail,
    launchingTaskName,
    setLaunchingTaskName,
    launchingTaskId,
    setLaunchingTaskId,
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
