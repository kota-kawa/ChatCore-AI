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
