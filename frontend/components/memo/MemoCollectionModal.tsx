import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageListContext,
  useMemoPageModalsContext,
} from "../../contexts/memo_page/memo_page_context";

// コレクション色のプリセット（新規作成と編集で共用） / Collection color presets shared by create and edit
const COLLECTION_COLOR_PRESETS = ["#6b7280", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9"];

type CollectionColorPickerProps = {
  id?: string;
  value: string;
  onChange: (color: string) => void;
};

// 色入力とプリセットの行 / The color input plus preset swatches row
function CollectionColorPicker({ id, value, onChange }: CollectionColorPickerProps) {
  const { t } = useTranslation();
  return (
    <div className="memo-collection-create__color-row">
      <label htmlFor={id}>{t("memo.color")}</label>
      <input type="color" id={id} value={value} onChange={(e) => onChange(e.target.value)} className="memo-collection-color-input" />
      <div className="memo-collection-presets">
        {COLLECTION_COLOR_PRESETS.map((c) => (
          <button
            type="button"
            key={c}
            className={`memo-collection-preset${value === c ? " is-active" : ""}`}
            style={{ background: c }}
            onClick={() => onChange(c)}
            aria-label={c}
            data-tooltip={c}
            data-tooltip-placement="top"
          />
        ))}
      </div>
    </div>
  );
}

// ── Collection management panel ──
// 共通モーダル面（cc-modal）に、新規作成フォームと既存コレクションの一覧を節として並べる。
// Shared modal surface (cc-modal) with the create form and the existing collection list as sections.
export function MemoCollectionModal() {
  const { collections } = useMemoPageListContext();
  const {
    isCollectionPanelOpen,
    setIsCollectionPanelOpen,
    newCollectionName,
    setNewCollectionName,
    newCollectionColor,
    setNewCollectionColor,
    collectionActionLoading,
    handleCreateCollection,
    editingCollectionId,
    setEditingCollectionId,
    editingCollectionName,
    setEditingCollectionName,
    editingCollectionColor,
    setEditingCollectionColor,
    handleUpdateCollection,
    handleDeleteCollection,
  } = useMemoPageModalsContext();
  const { t } = useTranslation();
  const close = () => setIsCollectionPanelOpen(false);
  return (
    <ModalShell
      isOpen={isCollectionPanelOpen}
      onClose={close}
      id="memo-collection-modal"
      className="cc-modal memo-modal-scope memo-collection-modal"
      labelledBy="collectionPanelTitle"
      initialFocusSelector=".memo-collection-create__input"
    >
      <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1}>
        <header className="cc-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="collectionPanelTitle">{t("memo.manageCollections")}</h2>
            <p className="cc-modal__lead">{t("memo.collectionDescription")}</p>
          </div>
          <ModalCloseButton label={t("common.close")} onClick={close} />
        </header>

        <div className="cc-modal__body memo-collection-modal__body">
          {/* Create new */}
          <section className="cc-modal__section memo-collection-create">
            <div className="cc-modal__section-head">
              <h3 className="cc-modal__section-title">{t("memo.create")}</h3>
            </div>
            <input
              type="text"
              className="memo-collection-create__input"
              value={newCollectionName}
              onChange={(e) => setNewCollectionName(e.target.value)}
              placeholder={t("memo.newCollectionName")}
              aria-label={t("memo.newCollectionName")}
              maxLength={100}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void handleCreateCollection(); } }}
            />
            <div className="memo-collection-create__footer">
              <CollectionColorPicker id="new-collection-color" value={newCollectionColor} onChange={setNewCollectionColor} />
              <button
                type="button"
                className="cc-modal__btn cc-modal__btn--primary memo-collection-create__btn"
                onClick={() => { void handleCreateCollection(); }}
                disabled={collectionActionLoading || !newCollectionName.trim()}
              >
                <i className="bi bi-plus-lg" aria-hidden="true"></i>{t("memo.create")}
              </button>
            </div>
          </section>

          {/* Collection list */}
          <section className="cc-modal__section">
            <div className="cc-modal__section-head">
              <h3 className="cc-modal__section-title">{t("memo.collections")}</h3>
              <span className="cc-modal__section-meta">{t("memo.items", { count: collections.length })}</span>
            </div>
            {collections.length === 0 && <p className="memo-collection-empty">{t("memo.noCollectionsYet")}</p>}
            <ul className="memo-collection-list">
              {collections.map((col) => (
                <li key={col.id} className="memo-collection-item">
                  {editingCollectionId === col.id ? (
                    <div className="memo-collection-item__edit">
                      <input
                        type="text"
                        className="memo-collection-create__input"
                        value={editingCollectionName}
                        onChange={(e) => setEditingCollectionName(e.target.value)}
                        aria-label={t("memo.newCollectionName")}
                        maxLength={100}
                      />
                      <CollectionColorPicker id={`edit-collection-color-${col.id}`} value={editingCollectionColor} onChange={setEditingCollectionColor} />
                      <div className="memo-collection-item__edit-actions">
                        <button type="button" className="cc-modal__btn cc-modal__btn--sm" onClick={() => setEditingCollectionId(null)}>{t("common.cancel")}</button>
                        <button type="button" className="cc-modal__btn cc-modal__btn--primary cc-modal__btn--sm" onClick={() => { void handleUpdateCollection(col.id); }} disabled={collectionActionLoading}>{t("common.save")}</button>
                      </div>
                    </div>
                  ) : (
                    <div className="memo-collection-item__row">
                      <span className="memo-collection-item__dot" style={{ background: col.color }}></span>
                      <span className="memo-collection-item__name">{col.name}</span>
                      <span className="memo-collection-item__count">{t("memo.items", { count: col.memo_count })}</span>
                      <button
                        type="button"
                        className="memo-collection-item__action"
                        onClick={() => { setEditingCollectionId(col.id); setEditingCollectionName(col.name); setEditingCollectionColor(col.color); }}
                        aria-label={t("common.edit")}
                        data-tooltip={t("common.edit")}
                        data-tooltip-placement="top"
                      >
                        <i className="bi bi-pencil" aria-hidden="true"></i>
                      </button>
                      <button
                        type="button"
                        className="memo-collection-item__action memo-collection-item__action--danger"
                        onClick={() => { void handleDeleteCollection(col.id, col.name); }}
                        disabled={collectionActionLoading}
                        aria-label={t("common.delete")}
                        data-tooltip={t("common.delete")}
                        data-tooltip-placement="top"
                      >
                        <i className="bi bi-trash3" aria-hidden="true"></i>
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </ModalShell>
  );
}
