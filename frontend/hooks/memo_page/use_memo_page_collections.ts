import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import useSWR, { type KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { createCollection, deleteCollection, loadCollections, updateCollection } from "../../lib/memo/api";
import type { Collection, FlashState, MemoListState } from "../../lib/memo/types";
import { showConfirmModal } from "../../scripts/core/alert_modal";

type UseMemoPageCollectionsParams = {
  isLoggedIn: boolean;
  activeCollectionId: number | null;
  setActiveCollectionId: Dispatch<SetStateAction<number | null>>;
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
};

// コレクション一覧の取得と、管理パネル（作成・更新・削除）の状態と操作
// Collection list fetch plus the management panel state and actions (create / update / delete)
export function useMemoPageCollections({
  isLoggedIn,
  activeCollectionId,
  setActiveCollectionId,
  mutate,
  showFlash,
}: UseMemoPageCollectionsParams) {
  const { t } = useTranslation();

  const { data: collections = [], mutate: mutateCollections } =
    useSWR<Collection[]>(isLoggedIn ? "/memo/api/collections" : null, loadCollections, {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
    });

  // Collection management panel
  const [isCollectionPanelOpen, setIsCollectionPanelOpen] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionColor, setNewCollectionColor] = useState("#6b7280");
  const [collectionActionLoading, setCollectionActionLoading] = useState(false);
  const [editingCollectionId, setEditingCollectionId] = useState<number | null>(null);
  const [editingCollectionName, setEditingCollectionName] = useState("");
  const [editingCollectionColor, setEditingCollectionColor] = useState("#6b7280");

  // 新しいコレクションを作成するハンドラー
  // Handler to create a new collection
  const handleCreateCollection = useCallback(async () => {
    const name = newCollectionName.trim();
    if (!name) { showFlash("error", t("memo.collectionNameRequired")); return; }
    setCollectionActionLoading(true);
    try {
      await createCollection({ name, color: newCollectionColor }, t("memo.collectionCreateFailed"));
      setNewCollectionName("");
      setNewCollectionColor("#6b7280");
      showFlash("success", t("memo.collectionCreated"));
      await mutateCollections();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionCreateFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [newCollectionColor, newCollectionName, mutateCollections, showFlash]);

  // 既存のコレクションを更新するハンドラー
  // Handler to update an existing collection
  const handleUpdateCollection = useCallback(async (collectionId: number) => {
    setCollectionActionLoading(true);
    try {
      await updateCollection(collectionId, { name: editingCollectionName, color: editingCollectionColor }, t("memo.collectionUpdateFailed"));
      setEditingCollectionId(null);
      showFlash("success", t("memo.collectionUpdated"));
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionUpdateFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [editingCollectionColor, editingCollectionName, mutate, mutateCollections, showFlash]);

  // コレクションを削除するハンドラー
  // Handler to delete a collection
  const handleDeleteCollection = useCallback(async (collectionId: number, name: string) => {
    const confirmed = await showConfirmModal(t("memo.collectionDeleteConfirm", { name }));
    if (!confirmed) return;
    setCollectionActionLoading(true);
    try {
      await deleteCollection(collectionId, t("memo.collectionDeleteFailed"));
      if (activeCollectionId === collectionId) setActiveCollectionId(null);
      showFlash("success", t("memo.collectionDeleted"));
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionDeleteFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [activeCollectionId, mutate, mutateCollections, showFlash]);

  const activeCollection = activeCollectionId !== null ? collections.find((c) => c.id === activeCollectionId) : null;

  return {
    collections,
    mutateCollections,
    activeCollection,
    isCollectionPanelOpen,
    setIsCollectionPanelOpen,
    newCollectionName,
    setNewCollectionName,
    newCollectionColor,
    setNewCollectionColor,
    collectionActionLoading,
    editingCollectionId,
    setEditingCollectionId,
    editingCollectionName,
    setEditingCollectionName,
    editingCollectionColor,
    setEditingCollectionColor,
    handleCreateCollection,
    handleUpdateCollection,
    handleDeleteCollection,
  };
}
