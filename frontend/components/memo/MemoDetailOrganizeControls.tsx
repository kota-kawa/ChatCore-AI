import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useMemoPageDetailContext, useMemoPageListContext } from "../../contexts/memo_page/memo_page_context";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { MemoSelect } from "./MemoSelect";

export function MemoDetailOrganizeControls() {
  const { t } = useTranslation();
  const { collections } = useMemoPageListContext();
  const {
    detailEditCollectionId, setDetailEditCollectionId,
    detailEditBackgroundColor, setDetailEditBackgroundColor,
  } = useMemoPageDetailContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || ref.current?.contains(target) || target.closest("[role='listbox']")) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  return (
    <details
      ref={ref}
      className="memo-modal__organize"
      open={open}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open || event.defaultPrevented) return;
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        ref.current?.querySelector("summary")?.focus();
      }}
    >
      <summary
        className="memo-modal__icon-btn"
        aria-label={t("memo.moreActions")}
        aria-expanded={open}
        onClick={(event) => { event.preventDefault(); setOpen((previous) => !previous); }}
      >
        <i className="bi bi-three-dots" aria-hidden="true" />
      </summary>
      <div className="memo-modal__organize-panel">
        {collections.length > 0 && (
          <div className="memo-modal__organize-field">
            <span>{t("memo.collections")}</span>
            <MemoSelect
              id="memo-detail-collection"
              ariaLabel={t("memo.collections")}
              className="memo-select--detail-collection"
              value={String(detailEditCollectionId ?? "")}
              onChange={(value) => setDetailEditCollectionId(value === "" ? null : Number(value))}
              options={[
                { value: "", label: t("memo.noCollection") },
                ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
              ]}
            />
          </div>
        )}
        <div className="memo-modal__organize-field">
          <span>{t("memo.backgroundColor")}</span>
          <div className="memo-modal__color-strip" role="listbox" aria-label={t("memo.backgroundColor")}>
            {MEMO_COLOR_OPTIONS.map((option) => (
              <button
                key={option.label}
                type="button"
                className={`memo-modal__color-option${(detailEditBackgroundColor || "") === option.value ? " is-active" : ""}`}
                style={{ "--palette-color": option.color } as CSSProperties}
                onClick={() => setDetailEditBackgroundColor(option.value || null)}
                role="option"
                aria-selected={(detailEditBackgroundColor || "") === option.value}
                aria-label={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
                data-tooltip={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
              >
                <span />
              </button>
            ))}
          </div>
        </div>
      </div>
    </details>
  );
}
