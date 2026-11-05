// ホーム画面の Skill 一覧の取得と、追加・有効/無効の切り替え・削除を扱うフック。
// Hook for the home page Skill list: fetching it, and adding, toggling, and deleting Skills.
import { useCallback, useMemo, useState, type FormEvent } from "react";
import useSWR from "swr";

import { useTranslation } from "../../contexts/locale_context";
import {
  createUserSkill,
  deleteUserSkill,
  fetchUserSkills,
  updateUserSkillState,
  type UserSkill,
} from "../../lib/chat_page/skill_api";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";

type UseHomePageSkillsOptions = {
  loggedIn: boolean;
};

// 一覧は SWR で取得し、更新系の操作は楽観的更新（先に画面を変え、失敗したら元に戻す）で反映する。
// The list is fetched with SWR, and write operations use optimistic updates (change the UI first, roll back on failure).
export function useHomePageSkills({ loggedIn }: UseHomePageSkillsOptions) {
  const { locale } = useTranslation();
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [skillName, setSkillName] = useState("");
  const [skillInstructions, setSkillInstructions] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [pendingSkillId, setPendingSkillId] = useState<number | null>(null);

  const { data: skills = [], error, isLoading, mutate } = useSWR<UserSkill[]>(
    loggedIn ? ["/api/skills", locale] : null,
    ([, requestLocale]) => fetchUserSkills().then((items) => {
      // キーにロケールを含めているのは、言語切り替え時に同じアカウントのデータを再取得し、古いエラー状態を残さないため。
      // The locale is part of the key so a language switch always revalidates
      // the same account data without retaining an old error state.
      void requestLocale;
      return items;
    }),
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const openAddModal = useCallback(() => {
    setSkillName("");
    setSkillInstructions("");
    setIsAddModalOpen(true);
  }, []);

  const closeAddModal = useCallback(() => {
    if (isSaving) return;
    setIsAddModalOpen(false);
  }, [isSaving]);

  const handleCreate = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = skillName.trim();
    const instructions = skillInstructions.trim();
    if (!name || !instructions || isSaving) return;

    setIsSaving(true);
    try {
      const created = await createUserSkill(name, instructions);
      await mutate((previous) => [...(previous ?? []), created], { revalidate: false });
      setIsAddModalOpen(false);
      setSkillName("");
      setSkillInstructions("");
    } catch (caught) {
      showToast(caught instanceof Error ? caught.message : "Skillの追加に失敗しました。", { variant: "error" });
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, mutate, skillInstructions, skillName]);

  // 保留中の操作が1件でもあれば二重実行を避けて何もしない。
  // While any operation is pending, do nothing so toggles cannot overlap.
  const handleToggle = useCallback(async (skill: UserSkill) => {
    if (pendingSkillId !== null) return;

    const nextEnabled = !skill.is_enabled;
    setPendingSkillId(skill.id);
    const previous = skills;
    await mutate(
      previousSkills => (previousSkills ?? []).map(item => item.id === skill.id ? { ...item, is_enabled: nextEnabled } : item),
      { revalidate: false },
    );

    try {
      const updated = await updateUserSkillState(skill.id, nextEnabled);
      await mutate(
        current => (current ?? []).map(item => item.id === skill.id ? updated : item),
        { revalidate: false },
      );
    } catch (caught) {
      await mutate(previous, { revalidate: false });
      showToast(caught instanceof Error ? caught.message : "Skillの状態を更新できませんでした。", { variant: "error" });
    } finally {
      setPendingSkillId(null);
    }
  }, [mutate, pendingSkillId, skills]);

  const handleDelete = useCallback(async (skill: UserSkill) => {
    if (!skill.can_delete) return;
    const confirmed = await showConfirmModal(
      locale === "en" ? `Delete “${skill.name}”?` : `「${skill.name}」を削除しますか？`,
    );
    if (!confirmed || pendingSkillId !== null) return;

    setPendingSkillId(skill.id);
    const previous = skills;
    await mutate(
      previousSkills => (previousSkills ?? []).filter(item => item.id !== skill.id),
      { revalidate: false },
    );
    try {
      await deleteUserSkill(skill.id);
    } catch (caught) {
      await mutate(previous, { revalidate: false });
      showToast(caught instanceof Error ? caught.message : "Skillの削除に失敗しました。", { variant: "error" });
    } finally {
      setPendingSkillId(null);
    }
  }, [locale, mutate, pendingSkillId, skills]);

  const retry = useCallback(() => {
    void mutate();
  }, [mutate]);

  return useMemo(() => ({
    skills,
    error,
    isLoading,
    isAddModalOpen,
    skillName,
    skillInstructions,
    isSaving,
    pendingSkillId,
    openAddModal,
    closeAddModal,
    setSkillName,
    setSkillInstructions,
    handleCreate,
    handleToggle,
    handleDelete,
    retry,
  }), [
    closeAddModal,
    error,
    handleCreate,
    handleDelete,
    handleToggle,
    isAddModalOpen,
    isLoading,
    isSaving,
    openAddModal,
    pendingSkillId,
    retry,
    skillInstructions,
    skillName,
    skills,
  ]);
}
