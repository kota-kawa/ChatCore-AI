import type { PromptResource, PromptResourceRole } from "./types";

export const SKILL_RESOURCE_ROLES: ReadonlyArray<{
  value: PromptResourceRole;
  label: string;
}> = [
  { value: "script", label: "スクリプト" },
  { value: "reference", label: "参照資料" },
  { value: "config", label: "設定" },
  { value: "other", label: "その他" }
];

export const MAX_SKILL_RESOURCES = 10;
export const MAX_SKILL_RESOURCE_CONTENT_LENGTH = 256 * 1024;

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  ".bash": "shell",
  ".c": "c",
  ".cc": "cpp",
  ".cpp": "cpp",
  ".cxx": "cpp",
  ".css": "css",
  ".go": "go",
  ".h": "c",
  ".hpp": "cpp",
  ".html": "html",
  ".java": "java",
  ".js": "javascript",
  ".json": "json",
  ".jsx": "javascript",
  ".kt": "kotlin",
  ".kts": "kotlin",
  ".lua": "lua",
  ".md": "markdown",
  ".mdx": "mdx",
  ".mjs": "javascript",
  ".php": "php",
  ".pl": "perl",
  ".proto": "protobuf",
  ".ps1": "powershell",
  ".py": "python",
  ".r": "r",
  ".rb": "ruby",
  ".rs": "rust",
  ".scss": "scss",
  ".sh": "shell",
  ".sql": "sql",
  ".svelte": "svelte",
  ".swift": "swift",
  ".toml": "toml",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".vue": "vue",
  ".xml": "xml",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".zsh": "shell"
};

export function inferSkillResourceLanguage(path: string): string {
  const normalizedPath = path.trim().toLowerCase();
  const fileName = normalizedPath.split("/").pop() || "";
  if (fileName === "dockerfile") return "dockerfile";
  const extensionIndex = fileName.lastIndexOf(".");
  if (extensionIndex < 0) return "text";
  return LANGUAGE_BY_EXTENSION[fileName.slice(extensionIndex)] || "text";
}

export function getSkillResourceRoleLabel(role: PromptResourceRole): string {
  return SKILL_RESOURCE_ROLES.find((candidate) => candidate.value === role)?.label || "その他";
}

function isPromptResourceRole(value: unknown): value is PromptResourceRole {
  return SKILL_RESOURCE_ROLES.some((role) => role.value === value);
}

export function normalizeSkillResources(
  resources: unknown,
  legacyPythonScript = ""
): PromptResource[] {
  const normalized = Array.isArray(resources)
    ? resources.flatMap((resource): PromptResource[] => {
        if (!resource || typeof resource !== "object") return [];
        const candidate = resource as Record<string, unknown>;
        if (typeof candidate.path !== "string" || typeof candidate.content !== "string") {
          return [];
        }
        const path = candidate.path.trim();
        if (!path) return [];
        const language =
          typeof candidate.language === "string" && candidate.language.trim()
            ? candidate.language.trim()
            : inferSkillResourceLanguage(path);
        return [
          {
            path,
            role: isPromptResourceRole(candidate.role) ? candidate.role : "other",
            language,
            content: candidate.content
          }
        ];
      })
    : [];

  if (normalized.length === 0 && legacyPythonScript) {
    return [
      {
        path: "scripts/main.py",
        role: "script",
        language: "python",
        content: legacyPythonScript
      }
    ];
  }
  return normalized;
}
