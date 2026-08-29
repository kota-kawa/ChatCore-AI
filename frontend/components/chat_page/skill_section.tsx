import { memo } from "react";

import { useHomePageSkills } from "../../hooks/chat_page/use_home_page_skills";
import { useTranslation } from "../../contexts/locale_context";
import { NewSkillModal } from "./modals/new_skill_modal";

type SkillSectionProps = {
  loggedIn: boolean;
};

function SkillSectionComponent({ loggedIn }: SkillSectionProps) {
  const { locale, t } = useTranslation();
  const skillsState = useHomePageSkills({ loggedIn });

  if (!loggedIn) return null;

  const {
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
  } = skillsState;

  return (
    <section className="skill-section" aria-labelledby="skill-selection-title" data-skill-count={skills.length}>
      <div className="skill-section__header">
        <div className="skill-section__heading">
          <p id="skill-selection-title" className="skill-section__title">
            <i className="bi bi-stars" aria-hidden="true"></i>
            <span>{t("home.skills")}</span>
          </p>
          <p className="skill-section__description">{t("home.skillsDescription")}</p>
        </div>
        <button
          type="button"
          className="skill-section__add"
          onClick={openAddModal}
          aria-label={t("home.addSkill")}
          data-tooltip={t("home.addSkill")}
          data-tooltip-placement="top"
        >
          <i className="bi bi-plus-lg" aria-hidden="true"></i>
        </button>
      </div>

      {isLoading && skills.length === 0 ? (
        <p className="skill-section__status" role="status">{t("home.skillsLoading")}</p>
      ) : error ? (
        <div className="skill-section__error" role="alert">
          <span>{t("home.skillsLoadFailed")}</span>
          <button type="button" onClick={retry}>{t("common.retry")}</button>
        </div>
      ) : skills.length === 0 ? (
        <button type="button" className="skill-section__empty" onClick={openAddModal}>
          <span className="skill-section__empty-icon" aria-hidden="true"><i className="bi bi-plus-circle"></i></span>
          <span>
            <strong>{t("home.skillsEmpty")}</strong>
            <small>{t("home.skillsEmptyDescription")}</small>
          </span>
        </button>
      ) : (
        <div className="skill-section__list" role="list" aria-label={t("home.skills")}>
          {skills.map((skill) => {
            const isPending = pendingSkillId === skill.id;
            const stateLabel = skill.is_enabled ? t("home.skillOn") : t("home.skillOff");
            return (
              <div className={`skill-chip-row ${skill.is_enabled ? "is-enabled" : "is-disabled"} ${skill.is_default ? "is-default" : ""}`.trim()} key={skill.id} role="listitem">
                <button
                  type="button"
                  className="skill-chip"
                  role="switch"
                  aria-checked={skill.is_enabled}
                  aria-label={locale === "en" ? `${skill.name}: ${skill.is_enabled ? "turn off" : "turn on"}` : `${skill.name}を${skill.is_enabled ? "オフ" : "オン"}`}
                  aria-busy={isPending ? "true" : undefined}
                  disabled={pendingSkillId !== null}
                  onClick={() => { void handleToggle(skill); }}
                >
                  <span className="skill-chip__dot" aria-hidden="true"></span>
                  <span className="skill-chip__name" title={skill.name}>{skill.name}</span>
                  {skill.is_default ? (
                    <span className="skill-chip__default" title={t("home.skillDefaultDescription")}>
                      <i className="bi bi-lock-fill" aria-hidden="true"></i>
                      {t("home.skillDefault")}
                    </span>
                  ) : null}
                  <span className="skill-chip__state">{stateLabel}</span>
                  <span className="skill-chip__switch" aria-hidden="true"><span></span></span>
                </button>
                {skill.can_delete ? (
                  <button
                    type="button"
                    className="skill-chip__delete"
                    aria-label={locale === "en" ? `Delete ${skill.name}` : `${skill.name}を削除`}
                    disabled={pendingSkillId !== null}
                    onClick={() => { void handleDelete(skill); }}
                  >
                    <i className="bi bi-x-lg" aria-hidden="true"></i>
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      <NewSkillModal
        isOpen={isAddModalOpen}
        isSaving={isSaving}
        name={skillName}
        instructions={skillInstructions}
        onClose={closeAddModal}
        onSubmit={(event) => { void handleCreate(event); }}
        setName={setSkillName}
        setInstructions={setSkillInstructions}
      />
    </section>
  );
}

export const SkillSection = memo(SkillSectionComponent);
SkillSection.displayName = "SkillSection";
