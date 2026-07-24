import type { PromptResource, PromptResourceRole } from "../../scripts/prompt_share/types";
import {
  inferSkillResourceLanguage,
  MAX_SKILL_RESOURCE_CONTENT_LENGTH,
  MAX_SKILL_RESOURCES,
  SKILL_RESOURCE_ROLES
} from "../../scripts/prompt_share/skill_resources";

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
          <h4>追加リソース（任意）</h4>
          <p>スクリプト、参照資料、設定ファイルなどを複数追加できます。</p>
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
            ? `上限 ${MAX_SKILL_RESOURCES}件`
            : "リソースを追加"}
        </button>
      </div>

      {resources.length === 0 ? (
        <p className="skill-resource-editor__empty">
          追加リソースはありません。SKILL定義だけでも投稿できます。
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
                <legend>リソース {index + 1}</legend>
                <button
                  type="button"
                  className="skill-resource-editor__remove"
                  aria-label={`リソース ${index + 1} を削除`}
                  onClick={() => {
                    setResources(resources.filter((_, resourceIndex) => resourceIndex !== index));
                    onEdit();
                  }}
                >
                  <i className="bi bi-trash3" aria-hidden="true"></i>
                  削除
                </button>

                <div className="skill-resource-editor__meta">
                  <div className="form-group">
                    <label htmlFor={pathId}>ファイルパス</label>
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
                    <label htmlFor={roleId}>役割</label>
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
                          {role.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label htmlFor={languageId}>言語</label>
                    <input
                      id={languageId}
                      type="text"
                      maxLength={64}
                      placeholder="拡張子から自動判定"
                      value={resource.language || ""}
                      onChange={(event) => {
                        updateResource(index, { language: event.target.value });
                      }}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor={contentId}>内容</label>
                  <textarea
                    id={contentId}
                    required
                    rows={8}
                    maxLength={MAX_SKILL_RESOURCE_CONTENT_LENGTH}
                    placeholder="リソースの内容を入力"
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
