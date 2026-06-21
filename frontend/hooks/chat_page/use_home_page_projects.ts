import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

import type { AttachedFile, Project, ProjectDetail } from "../../lib/chat_page/types";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { extractApiErrorMessage, readJsonBodySafe } from "../../scripts/core/runtime_validation";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";

type UseHomePageProjectsParams = {
  loggedIn: boolean;
  // 新規チャット作成時に紐づけるプロジェクトIDを保持する ref（room actions が読み取る）。
  // Ref holding the project id to attach to the next created chat (read by room actions).
  pendingProjectIdRef: MutableRefObject<number | null>;
  setPendingProjectId: Dispatch<SetStateAction<number | null>>;
};

// プロジェクト（ChatGPT/Claude のプロジェクト相当）の一覧・詳細・CRUD を司るフック。
// Hook owning the list, detail, and CRUD of projects (ChatGPT/Claude-style workspaces).
export function useHomePageProjects({
  loggedIn,
  pendingProjectIdRef,
  setPendingProjectId,
}: UseHomePageProjectsParams) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isProjectsLoading, setIsProjectsLoading] = useState(false);
  // 詳細オーバーレイの対象プロジェクトID（null で閉じている）。
  // Target project id for the detail overlay (null = closed).
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [activeProjectDetail, setActiveProjectDetail] = useState<ProjectDetail | null>(null);
  const [isProjectDetailLoading, setIsProjectDetailLoading] = useState(false);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [isUploadingProjectFiles, setIsUploadingProjectFiles] = useState(false);

  const loadProjects = useCallback(async (): Promise<Project[]> => {
    if (!loggedIn) {
      setProjects([]);
      return [];
    }
    setIsProjectsLoading(true);
    try {
      const response = await resilientFetch("/api/projects", { credentials: "same-origin" });
      const payload = (await readJsonBodySafe(response)) as { projects?: Project[]; error?: string };
      if (!response.ok || payload.error) {
        throw new Error(extractApiErrorMessage(payload, "プロジェクト一覧の取得に失敗しました。", response.status));
      }
      const nextProjects = payload.projects ?? [];
      setProjects(nextProjects);
      return nextProjects;
    } catch (error) {
      console.error("プロジェクト一覧取得失敗:", error);
      return [];
    } finally {
      setIsProjectsLoading(false);
    }
  }, [loggedIn]);

  // ログイン状態が確定したらプロジェクト一覧を読み込む。
  // Load the project list once the user is known to be logged in.
  useEffect(() => {
    if (loggedIn) {
      void loadProjects();
    } else {
      setProjects([]);
      setActiveProjectId(null);
      setActiveProjectDetail(null);
    }
  }, [loadProjects, loggedIn]);

  const refreshProjectDetail = useCallback(async (projectId: number): Promise<ProjectDetail | null> => {
    setIsProjectDetailLoading(true);
    try {
      const response = await resilientFetch(`/api/projects/${projectId}`, { credentials: "same-origin" });
      const payload = (await readJsonBodySafe(response)) as { project?: ProjectDetail; error?: string };
      if (!response.ok || payload.error || !payload.project) {
        throw new Error(extractApiErrorMessage(payload, "プロジェクトの取得に失敗しました。", response.status));
      }
      setActiveProjectDetail(payload.project);
      return payload.project;
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
      return null;
    } finally {
      setIsProjectDetailLoading(false);
    }
  }, []);

  const openProject = useCallback(
    (projectId: number) => {
      setActiveProjectId(projectId);
      setActiveProjectDetail(null);
      void refreshProjectDetail(projectId);
    },
    [refreshProjectDetail],
  );

  const closeProject = useCallback(() => {
    setActiveProjectId(null);
    setActiveProjectDetail(null);
  }, []);

  const openNewProjectModal = useCallback(() => setIsProjectModalOpen(true), []);
  const closeNewProjectModal = useCallback(() => setIsProjectModalOpen(false), []);

  const createProject = useCallback(
    async (name: string, instructions: string): Promise<Project | null> => {
      setIsSavingProject(true);
      try {
        const response = await resilientFetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ name, instructions }),
        });
        const payload = (await readJsonBodySafe(response)) as { project?: Project; error?: string };
        if (!response.ok || payload.error || !payload.project) {
          throw new Error(extractApiErrorMessage(payload, "プロジェクトの作成に失敗しました。", response.status));
        }
        await loadProjects();
        setIsProjectModalOpen(false);
        showToast("プロジェクトを作成しました。", { variant: "success" });
        return payload.project;
      } catch (error) {
        showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
        return null;
      } finally {
        setIsSavingProject(false);
      }
    },
    [loadProjects],
  );

  const updateProject = useCallback(
    async (projectId: number, fields: { name?: string; instructions?: string }): Promise<boolean> => {
      setIsSavingProject(true);
      try {
        const response = await resilientFetch("/api/update_project", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ project_id: projectId, ...fields }),
        });
        const payload = (await readJsonBodySafe(response)) as { project?: Project; error?: string };
        if (!response.ok || payload.error) {
          throw new Error(extractApiErrorMessage(payload, "プロジェクトの更新に失敗しました。", response.status));
        }
        await Promise.all([loadProjects(), refreshProjectDetail(projectId)]);
        showToast("プロジェクトを更新しました。", { variant: "success" });
        return true;
      } catch (error) {
        showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
        return false;
      } finally {
        setIsSavingProject(false);
      }
    },
    [loadProjects, refreshProjectDetail],
  );

  const deleteProject = useCallback(
    async (projectId: number, projectName: string): Promise<void> => {
      const confirmed = await showConfirmModal(
        `「${projectName}」を削除しますか？\n配下のチャットは削除されず、プロジェクト未所属になります。`,
      );
      if (!confirmed) return;

      try {
        const response = await resilientFetch("/api/delete_project", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ project_id: projectId }),
        });
        const payload = (await readJsonBodySafe(response)) as { error?: string };
        if (!response.ok || payload.error) {
          throw new Error(extractApiErrorMessage(payload, "プロジェクトの削除に失敗しました。", response.status));
        }
        if (activeProjectId === projectId) {
          closeProject();
        }
        await loadProjects();
        showToast("プロジェクトを削除しました。", { variant: "success" });
      } catch (error) {
        showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
      }
    },
    [activeProjectId, closeProject, loadProjects],
  );

  const uploadProjectFiles = useCallback(
    async (projectId: number, files: AttachedFile[]): Promise<boolean> => {
      if (files.length === 0) return false;
      setIsUploadingProjectFiles(true);
      try {
        const response = await resilientFetch(`/api/projects/${projectId}/files`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            files: files.map((f) => ({
              name: f.name,
              content: f.content ?? "",
              media_type: f.mediaType ?? "",
              data_base64: f.dataBase64 ?? "",
            })),
          }),
        });
        const payload = (await readJsonBodySafe(response)) as { error?: string };
        if (!response.ok || payload.error) {
          throw new Error(extractApiErrorMessage(payload, "ファイルの追加に失敗しました。", response.status));
        }
        await Promise.all([refreshProjectDetail(projectId), loadProjects()]);
        showToast("ナレッジを追加しました。", { variant: "success" });
        return true;
      } catch (error) {
        showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
        return false;
      } finally {
        setIsUploadingProjectFiles(false);
      }
    },
    [loadProjects, refreshProjectDetail],
  );

  const deleteProjectFile = useCallback(
    async (projectId: number, fileId: number): Promise<void> => {
      try {
        const response = await resilientFetch("/api/delete_project_file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ file_id: fileId }),
        });
        const payload = (await readJsonBodySafe(response)) as { error?: string };
        if (!response.ok || payload.error) {
          throw new Error(extractApiErrorMessage(payload, "ファイルの削除に失敗しました。", response.status));
        }
        await Promise.all([refreshProjectDetail(projectId), loadProjects()]);
      } catch (error) {
        showToast(error instanceof Error ? error.message : String(error), { variant: "error" });
      }
    },
    [loadProjects, refreshProjectDetail],
  );

  // 「このプロジェクトで新規チャット」: 次の作成チャットに紐づけるIDを記録する。
  // "New chat in this project": record the id to attach to the next created chat.
  const setNewChatProject = useCallback(
    (projectId: number | null) => {
      pendingProjectIdRef.current = projectId;
      setPendingProjectId(projectId);
    },
    [pendingProjectIdRef, setPendingProjectId],
  );

  return {
    projects,
    isProjectsLoading,
    activeProjectId,
    activeProjectDetail,
    isProjectDetailLoading,
    isProjectModalOpen,
    isSavingProject,
    isUploadingProjectFiles,
    loadProjects,
    openProject,
    closeProject,
    refreshProjectDetail,
    openNewProjectModal,
    closeNewProjectModal,
    createProject,
    updateProject,
    deleteProject,
    uploadProjectFiles,
    deleteProjectFile,
    setNewChatProject,
  };
}
