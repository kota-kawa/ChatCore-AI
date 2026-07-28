import type { PromptResource, PromptResourceRole } from "../../scripts/prompt_share/types";
import {
  inferSkillResourceLanguage,
  getSkillResourceRoleLabel,
  MAX_SKILL_RESOURCE_CONTENT_LENGTH,
  MAX_SKILL_RESOURCES,
  SKILL_RESOURCE_ROLES
} from "../../scripts/prompt_share/skill_resources";
import { useTranslation } from "../../contexts/locale_context";

type SkillResourceEditorProps = {
  resources: PromptResource[];
  setResources: (resources: PromptResource[]) => void;
  onEdit: () => void;
};

const EMPTY_RESOURCE: PromptResource = {
  path: "",
  role: "script",
  language: "text",
  content: ""
};

export function SkillResourceEditor({
  resources,
  setResources,
  onEdit
}: SkillResourceEditorProps) {
  const { locale, t } = useTranslation();
  const updateResource = (index: number, patch: Partial<PromptResource>) => {
    setResources(
      resources.map((resource, resourceIndex) =>
        resourceIndex === index ? { ...resource, ...patch } : resource
      )
    );
    onEdit();
  };

  return (
    <div className="skill-resource-editor">
      <div className="skill-resource-editor__header">
        <div>
          <h4>{t("promptShare.resourceOptional")}</h4>
          <p>{t("promptShare.resourceHelp")}</p>
        </div>
        <button
          type="button"
          className="skill-resource-editor__add"
          disabled={resources.length >= MAX_SKILL_RESOURCES}
          onClick={() => {
            setResources([...resources, { ...EMPTY_RESOURCE }]);
            onEdit();
          }}
        >
          <i className="bi bi-plus-lg" aria-hidden="true"></i>
          {resources.length >= MAX_SKILL_RESOURCES
            ? t("promptShare.resourceLimit", { count: MAX_SKILL_RESOURCES })
            : t("promptShare.addResource")}
        </button>
      </div>

      {resources.length === 0 ? (
        <p className="skill-resource-editor__empty">
          {t("promptShare.noResources")}
        </p>
      ) : (
        <div className="skill-resource-editor__list">
          {resources.map((resource, index) => {
            const pathId = `skill-resource-path-${index}`;
            const roleId = `skill-resource-role-${index}`;
            const languageId = `skill-resource-language-${index}`;
            const contentId = `skill-resource-content-${index}`;
            return (
              <fieldset className="skill-resource-editor__item" key={index}>
                <legend>{t("promptShare.resourceNumber", { number: index + 1 })}</legend>
                <button
                  type="button"
                  className="skill-resource-editor__remove"
                  aria-label={t("promptShare.removeResource", { number: index + 1 })}
                  onClick={() => {
                    setResources(resources.filter((_, resourceIndex) => resourceIndex !== index));
                    onEdit();
                  }}
                >
                  <i className="bi bi-trash3" aria-hidden="true"></i>
                  {t("common.delete")}
                </button>

                <div className="skill-resource-editor__meta">
                  <div className="form-group">
                    <label htmlFor={pathId}>{t("promptShare.filePath")}</label>
                    <input
                      id={pathId}
                      type="text"
                      required
                      maxLength={255}
                      placeholder="scripts/run.ts"
                      value={resource.path}
                      onChange={(event) => {
                        const path = event.target.value;
                        updateResource(index, {
                          path,
                          language: inferSkillResourceLanguage(path)
                        });
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor={roleId}>{t("promptShare.role")}</label>
                    <select
                      id={roleId}
                      value={resource.role}
                      onChange={(event) => {
                        updateResource(index, {
                          role: event.target.value as PromptResourceRole
                        });
                      }}
                    >
                      {SKILL_RESOURCE_ROLES.map((role) => (
                        <option key={role.value} value={role.value}>
                          {getSkillResourceRoleLabel(role.value, locale)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label htmlFor={languageId}>{t("promptShare.language")}</label>
                    <input
                      id={languageId}
                      type="text"
                      maxLength={64}
                      placeholder={t("promptShare.languageAuto")}
                      value={resource.language || ""}
                      onChange={(event) => {
                        updateResource(index, { language: event.target.value });
                      }}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor={contentId}>{t("promptShare.contentLabel")}</label>
                  <textarea
                    id={contentId}
                    required
                    rows={8}
                    maxLength={MAX_SKILL_RESOURCE_CONTENT_LENGTH}
                    placeholder={t("promptShare.resourceContent")}
                    value={resource.content}
                    onChange={(event) => {
                      updateResource(index, { content: event.target.value });
                    }}
                  ></textarea>
                </div>
              </fieldset>
            );
          })}
        </div>
      )}
    </div>
  );
}
