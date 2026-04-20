import Head from "next/head";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent
} from "react";

import "../scripts/core/csrf";
import { PasskeyCancelledError, browserSupportsPasskeys, registerPasskey } from "../scripts/core/passkeys";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";
import { InlineLoading } from "../components/ui/inline_loading";
import { formatDateTime } from "../lib/datetime";
import {
  parseMyPromptsResponse,
  parsePromptListResponse,
  parsePromptManageMutationResponse,
  type PromptListEntry,
  type PromptRecord
} from "../scripts/user/settings/types";
import { truncateTitle } from "../scripts/user/settings/utils";

type SettingsSection = "profile" | "prompts" | "prompt-list" | "notifications" | "security";

type SettingsNavItem = {
  section: SettingsSection;
  iconClass: string;
  label: string;
};

type ProfileFormState = {
  username: string;
  email: string;
  bio: string;
  llmProfileContext: string;
};

type ProfileSaveStatus = {
  tone: "success" | "error";
  message: string;
};

type EditPromptFormState = {
  id: string;
  title: string;
  category: string;
  content: string;
  inputExamples: string;
  outputExamples: string;
};

type PasskeyRecord = {
  id: number;
  label: string;
  credentialDeviceType: string;
  credentialBackedUp: boolean;
  createdAt: string;
  lastUsedAt: string;
};

const PROFILE_SAVE_EFFECT_DURATION_MS = 2200;

const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { section: "profile", iconClass: "bi bi-person-circle", label: "プロフィール設定" },
  { section: "prompts", iconClass: "bi bi-shield-lock", label: "プロンプト管理" },
  { section: "prompt-list", iconClass: "bi bi-list-stars", label: "プロンプトリスト" },
  { section: "notifications", iconClass: "bi bi-bell", label: "通知設定" },
  { section: "security", iconClass: "bi bi-key", label: "セキュリティ" }
];

const DEFAULT_AVATAR_URL = "/static/user-icon.png";
const PASSKEY_INITIAL_SUPPORT_TEXT = "このブラウザの対応状況を確認しています。";

function asString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function asIdString(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "";
}

function toDisplayDate(rawDate?: string): string {
  return formatDateTime(rawDate) || rawDate || "";
}

function normalizePreviewText(value?: string): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function normalizePasskeyRecords(rawPasskeys: unknown[]): PasskeyRecord[] {
  return rawPasskeys
    .map((rawPasskey) => {
      const passkey = typeof rawPasskey === "object" && rawPasskey !== null
        ? (rawPasskey as Record<string, unknown>)
        : {};
      const id = Number(passkey.id);
      if (!Number.isFinite(id)) {
        return null;
      }
      const label = typeof passkey.label === "string" && passkey.label.trim()
        ? passkey.label.trim()
        : "保存済みPasskey";
      return {
        id,
        label,
        credentialDeviceType: typeof passkey.credential_device_type === "string"
          ? passkey.credential_device_type
          : "不明",
        credentialBackedUp: Boolean(passkey.credential_backed_up),
        createdAt: typeof passkey.created_at === "string" ? passkey.created_at : "",
        lastUsedAt: typeof passkey.last_used_at === "string" ? passkey.last_used_at : ""
      };
    })
    .filter((passkey): passkey is PasskeyRecord => passkey !== null);
}

function formatPasskeyDateTime(value: string): string {
  if (!value) {
    return "未使用";
  }
  return formatDateTime(value) || "未使用";
}

function buildDefaultLlmProfileContext(profile: Pick<ProfileFormState, "username" | "email" | "bio">): string {
  const lines: string[] = [];
  const username = profile.username.trim();
  const email = profile.email.trim();
  const bio = profile.bio.trim();

  if (username) {
    lines.push(`名前: ${username}`);
  }
  if (email) {
    lines.push(`メールアドレス: ${email}`);
  }
  if (bio) {
    lines.push(`自己紹介: ${bio}`);
  }

  return lines.join("\n");
}

function SettingsSidebar({
  activeSection,
  onSectionSelect
}: {
  activeSection: SettingsSection;
  onSectionSelect: (section: SettingsSection) => void;
}) {
  return (
    <nav className="settings-sidebar">
      <div className="sidebar-header">
        <h3>設定</h3>
      </div>

      <ul className="nav-menu">
        {SETTINGS_NAV_ITEMS.map((item) => (
          <li key={item.section}>
            <button
              type="button"
              className={`nav-link${activeSection === item.section ? " active" : ""}`}
              data-section={item.section}
              aria-current={activeSection === item.section ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onSectionSelect(item.section);
              }}
            >
              <i className={item.iconClass}></i> {item.label}
            </button>
          </li>
        ))}
      </ul>

      <div className="sidebar-footer">
        <p>&copy; 2025 YourApp</p>
      </div>
    </nav>
  );
}

function PromptCard({
  prompt,
  onEdit,
  onDelete
}: {
  prompt: PromptRecord;
  onEdit: (prompt: PromptRecord) => void;
  onDelete: (prompt: PromptRecord) => void;
}) {
  const promptId = asIdString(prompt.id);
  const contentPreview = normalizePreviewText(prompt.content);
  const inputPreview = normalizePreviewText(prompt.inputExamples);
  const outputPreview = normalizePreviewText(prompt.outputExamples);
  const categoryLabel = normalizePreviewText(prompt.category) || "未分類";
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : "日時未設定";

  return (
    <article className="prompt-card" data-prompt-id={promptId}>
      <div className="prompt-card__header">
        <div className="prompt-card__eyebrow">
          <span className="prompt-card__chip prompt-card__chip--category">{categoryLabel}</span>
          <span className="prompt-card__meta-item">
            <i className="bi bi-calendar3" aria-hidden="true"></i>
            {createdAtLabel}
          </span>
        </div>
        <h3 className="prompt-card__title" title={prompt.title}>{truncateTitle(prompt.title)}</h3>
      </div>
      <p className="prompt-card__content" title={prompt.content}>{contentPreview || "内容はまだありません。"}</p>
      {(inputPreview || outputPreview) ? (
        <div className="prompt-card__details">
          {inputPreview ? (
            <div className="prompt-card__detail">
              <span className="prompt-card__detail-label">入力例</span>
              <p className="prompt-card__detail-text" title={prompt.inputExamples}>{inputPreview}</p>
            </div>
          ) : null}
          {outputPreview ? (
            <div className="prompt-card__detail">
              <span className="prompt-card__detail-label">出力例</span>
              <p className="prompt-card__detail-text" title={prompt.outputExamples}>{outputPreview}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="btn-group prompt-card__actions">
        <button
          type="button"
          className="btn btn-sm btn-warning edit-btn"
          data-id={promptId}
          onClick={() => onEdit(prompt)}
        >
          <i className="bi bi-pencil"></i> 編集
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger delete-btn"
          data-id={promptId}
          onClick={() => onDelete(prompt)}
        >
          <i className="bi bi-trash"></i> 削除
        </button>
      </div>
    </article>
  );
}

function PromptListCard({
  entry,
  onDelete
}: {
  entry: PromptListEntry;
  onDelete: (entry: PromptListEntry) => void;
}) {
  const entryId = asIdString(entry.id);
  const contentPreview = normalizePreviewText(entry.content);
  const inputPreview = normalizePreviewText(entry.inputExamples);
  const outputPreview = normalizePreviewText(entry.outputExamples);
  const categoryLabel = normalizePreviewText(entry.category);
  const createdAtLabel = entry.createdAt ? toDisplayDate(entry.createdAt) : "日時未設定";

  return (
    <article className="prompt-card" data-prompt-list-entry-id={entryId}>
      <div className="prompt-card__header">
        <div className="prompt-card__eyebrow">
          <span className="prompt-card__chip prompt-card__chip--saved">保存済み</span>
          {categoryLabel ? <span className="prompt-card__chip prompt-card__chip--category">{categoryLabel}</span> : null}
        </div>
        <h3 className="prompt-card__title" title={entry.title}>{truncateTitle(entry.title)}</h3>
      </div>
      <p className="prompt-card__content" title={entry.content}>{contentPreview || "内容はまだありません。"}</p>
      <div className="prompt-card__meta-row">
        <span className="prompt-card__meta-item">
          <i className="bi bi-bookmark-check" aria-hidden="true"></i>
          {createdAtLabel}
        </span>
      </div>
      {(inputPreview || outputPreview) ? (
        <div className="prompt-card__details">
          {inputPreview ? (
            <div className="prompt-card__detail">
              <span className="prompt-card__detail-label">入力例</span>
              <p className="prompt-card__detail-text" title={entry.inputExamples}>{inputPreview}</p>
            </div>
          ) : null}
          {outputPreview ? (
            <div className="prompt-card__detail">
              <span className="prompt-card__detail-label">出力例</span>
              <p className="prompt-card__detail-text" title={entry.outputExamples}>{outputPreview}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="btn-group prompt-card__actions">
        <button
          type="button"
          className="btn btn-sm btn-danger remove-prompt-list-btn"
          data-id={entryId}
          onClick={() => onDelete(entry)}
        >
          <i className="bi bi-trash"></i> 削除
        </button>
      </div>
    </article>
  );
}

function EditPromptModal({
  formState,
  saving,
  onClose,
  onChange,
  onSubmit
}: {
  formState: EditPromptFormState;
  saving: boolean;
  onClose: () => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div
      id="editModal"
      className="modal show"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      style={{ display: "block", backgroundColor: "rgba(15, 23, 42, 0.5)" }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !saving) {
          onClose();
        }
      }}
    >
      <div className="modal-dialog modal-dialog-centered modal-dialog-scrollable" role="document">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">
              <i className="bi bi-pencil-square me-2"></i>プロンプト編集
            </h5>
            <button
              type="button"
              className="btn-close"
              aria-label="Close"
              onClick={onClose}
              disabled={saving}
            ></button>
          </div>

          <div className="modal-body">
            <form id="editForm" className="modal-form" onSubmit={onSubmit}>
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <div className="form-group">
                <label htmlFor="editTitle" className="form-label">
                  タイトル
                </label>
                <input
                  type="text"
                  className="form-control input-field"
                  id="editTitle"
                  name="title"
                  required
                  value={formState.title}
                  onChange={onChange}
                  disabled={saving}
                />
              </div>

              <div className="form-group">
                <label htmlFor="editCategory" className="form-label">
                  カテゴリ
                </label>
                <input
                  type="text"
                  className="form-control input-field"
                  id="editCategory"
                  name="category"
                  required
                  value={formState.category}
                  onChange={onChange}
                  disabled={saving}
                />
              </div>

              <div className="form-group">
                <label htmlFor="editContent" className="form-label">
                  内容
                </label>
                <textarea
                  className="form-control input-field"
                  id="editContent"
                  name="content"
                  rows={5}
                  required
                  value={formState.content}
                  onChange={onChange}
                  disabled={saving}
                ></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editInputExamples" className="form-label">
                  入力例
                </label>
                <textarea
                  className="form-control input-field"
                  id="editInputExamples"
                  name="inputExamples"
                  rows={3}
                  value={formState.inputExamples}
                  onChange={onChange}
                  disabled={saving}
                ></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editOutputExamples" className="form-label">
                  出力例
                </label>
                <textarea
                  className="form-control input-field"
                  id="editOutputExamples"
                  name="outputExamples"
                  rows={3}
                  value={formState.outputExamples}
                  onChange={onChange}
                  disabled={saving}
                ></textarea>
              </div>

              <div className="form-actions">
                <button type="submit" className="btn btn-primary w-100" disabled={saving}>
                  <i className="bi bi-save me-2"></i>{saving ? "更新中..." : "更新する"}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function UserSettingsPage() {
  const [activeSection, setActiveSection] = useState<SettingsSection>("profile");

  const [profileForm, setProfileForm] = useState<ProfileFormState>({
    username: "",
    email: "",
    bio: "",
    llmProfileContext: ""
  });
  const [initialProfileForm, setInitialProfileForm] = useState<ProfileFormState>({
    username: "",
    email: "",
    bio: "",
    llmProfileContext: ""
  });
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState(DEFAULT_AVATAR_URL);
  const [initialAvatarUrl, setInitialAvatarUrl] = useState(DEFAULT_AVATAR_URL);
  const [selectedAvatarFile, setSelectedAvatarFile] = useState<File | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaveStatus, setProfileSaveStatus] = useState<ProfileSaveStatus | null>(null);
  const [profileSaveEffectToken, setProfileSaveEffectToken] = useState(0);
  const [profileSaveEffectActive, setProfileSaveEffectActive] = useState(false);
  const [llmProfileContextUsesGeneratedDefault, setLlmProfileContextUsesGeneratedDefault] = useState(false);
  const [initialLlmProfileContextUsesGeneratedDefault, setInitialLlmProfileContextUsesGeneratedDefault] = useState(false);

  const [myPrompts, setMyPrompts] = useState<PromptRecord[]>([]);
  const [myPromptsLoading, setMyPromptsLoading] = useState(false);
  const [myPromptsError, setMyPromptsError] = useState<string | null>(null);

  const [promptListEntries, setPromptListEntries] = useState<PromptListEntry[]>([]);
  const [promptListLoading, setPromptListLoading] = useState(false);
  const [promptListError, setPromptListError] = useState<string | null>(null);

  const [editPromptForm, setEditPromptForm] = useState<EditPromptFormState | null>(null);
  const [promptSaving, setPromptSaving] = useState(false);

  const [passkeySupported, setPasskeySupported] = useState(true);
  const [passkeySupportStatus, setPasskeySupportStatus] = useState(PASSKEY_INITIAL_SUPPORT_TEXT);
  const [passkeys, setPasskeys] = useState<PasskeyRecord[]>([]);
  const [passkeysLoading, setPasskeysLoading] = useState(false);
  const [registeringPasskey, setRegisteringPasskey] = useState(false);
  const [deletingPasskeyId, setDeletingPasskeyId] = useState<number | null>(null);

  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  const profileSaveEffectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSectionActive = useCallback(
    (section: SettingsSection) => activeSection === section,
    [activeSection]
  );

  const loadProfile = useCallback(async () => {
    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/profile",
        { credentials: "same-origin" },
        { defaultMessage: "プロフィール情報の取得に失敗しました。" }
      );

      const nextProfile: ProfileFormState = {
        username: asString(payload.username),
        email: asString(payload.email),
        bio: asString(payload.bio),
        llmProfileContext: ""
      };
      const rawLlmProfileContext = payload.llm_profile_context;
      const shouldUseGeneratedDefault = rawLlmProfileContext === null || rawLlmProfileContext === undefined;
      const nextLlmProfileContext = shouldUseGeneratedDefault
        ? buildDefaultLlmProfileContext(nextProfile)
        : asString(rawLlmProfileContext);
      const nextResolvedProfile: ProfileFormState = {
        ...nextProfile,
        llmProfileContext: nextLlmProfileContext
      };
      const nextAvatarUrl = asString(payload.avatar_url) || DEFAULT_AVATAR_URL;

      setProfileForm(nextResolvedProfile);
      setInitialProfileForm(nextResolvedProfile);
      setAvatarPreviewUrl(nextAvatarUrl);
      setInitialAvatarUrl(nextAvatarUrl);
      setSelectedAvatarFile(null);
      setLlmProfileContextUsesGeneratedDefault(shouldUseGeneratedDefault);
      setInitialLlmProfileContextUsesGeneratedDefault(shouldUseGeneratedDefault);
      if (avatarInputRef.current) {
        avatarInputRef.current.value = "";
      }
    } catch (error) {
      console.error("loadProfile:", error instanceof Error ? error.message : String(error));
    }
  }, []);

  const loadMyPrompts = useCallback(async () => {
    setMyPromptsLoading(true);
    setMyPromptsError(null);
    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_manage/api/my_prompts",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトの取得に失敗しました。"
        }
      );
      setMyPrompts(parseMyPromptsResponse(payload));
    } catch (error) {
      setMyPrompts([]);
      setMyPromptsError(error instanceof Error ? error.message : "プロンプトの取得に失敗しました。");
    } finally {
      setMyPromptsLoading(false);
    }
  }, []);

  const loadPromptList = useCallback(async () => {
    setPromptListLoading(true);
    setPromptListError(null);
    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_manage/api/prompt_list",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトリストの取得に失敗しました。"
        }
      );
      setPromptListEntries(parsePromptListResponse(payload));
    } catch (error) {
      setPromptListEntries([]);
      setPromptListError(error instanceof Error ? error.message : "プロンプトリストの取得に失敗しました。");
    } finally {
      setPromptListLoading(false);
    }
  }, []);

  const loadPasskeys = useCallback(async () => {
    if (!browserSupportsPasskeys()) {
      setPasskeySupported(false);
      setPasskeySupportStatus("このブラウザではPasskeyを利用できません。");
      setPasskeys([]);
      return;
    }

    setPasskeySupported(true);
    setPasskeySupportStatus("このブラウザはPasskeyに対応しています。");
    setPasskeysLoading(true);

    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/passkeys",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "Passkey一覧の取得に失敗しました。",
          hasApplicationError: (data) => data.status === "fail"
        }
      );
      const passkeyRecords = Array.isArray(payload.passkeys) ? payload.passkeys : [];
      setPasskeys(normalizePasskeyRecords(passkeyRecords));
    } catch (error) {
      setPasskeys([]);
      alert(error instanceof Error ? error.message : "Passkey一覧の取得に失敗しました。");
    } finally {
      setPasskeysLoading(false);
    }
  }, []);

  useEffect(() => {
    document.body.classList.add("settings-page");
    void loadProfile();
    void loadPasskeys();

    return () => {
      if (profileSaveEffectTimeoutRef.current) {
        clearTimeout(profileSaveEffectTimeoutRef.current);
      }
      document.body.classList.remove("settings-page");
      document.body.classList.remove("modal-open");
    };
  }, [loadPasskeys, loadProfile]);

  useEffect(() => {
    if (profileSaveEffectToken === 0) {
      return;
    }

    if (profileSaveEffectTimeoutRef.current) {
      clearTimeout(profileSaveEffectTimeoutRef.current);
    }

    setProfileSaveEffectActive(true);
    profileSaveEffectTimeoutRef.current = setTimeout(() => {
      setProfileSaveEffectActive(false);
      profileSaveEffectTimeoutRef.current = null;
    }, PROFILE_SAVE_EFFECT_DURATION_MS);

    return () => {
      if (profileSaveEffectTimeoutRef.current) {
        clearTimeout(profileSaveEffectTimeoutRef.current);
        profileSaveEffectTimeoutRef.current = null;
      }
    };
  }, [profileSaveEffectToken]);

  useEffect(() => {
    if (!editPromptForm) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !promptSaving) {
        setEditPromptForm(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [editPromptForm, promptSaving]);

  useEffect(() => {
    document.body.classList.toggle("modal-open", Boolean(editPromptForm));
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [editPromptForm]);

  const handleSectionSelect = useCallback((section: SettingsSection) => {
    setActiveSection(section);

    if (section === "prompts") {
      void loadMyPrompts();
      return;
    }
    if (section === "prompt-list") {
      void loadPromptList();
      return;
    }
    if (section === "security") {
      void loadPasskeys();
    }
  }, [loadMyPrompts, loadPasskeys, loadPromptList]);

  const handleProfileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const { name, value } = event.target;
      setProfileSaveStatus(null);
      setProfileSaveEffectActive(false);
      setProfileForm((prev) => {
        const nextProfile = {
          ...prev,
          [name]: value
        };

        if (name === "llmProfileContext") {
          setLlmProfileContextUsesGeneratedDefault(false);
          return nextProfile;
        }

        if (llmProfileContextUsesGeneratedDefault) {
          nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
        }
        return nextProfile;
      });
    },
    [llmProfileContextUsesGeneratedDefault]
  );

  const handleAvatarFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setAvatarPreviewUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);

    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
    setSelectedAvatarFile(file);
  }, []);

  const handleProfileCancel = useCallback(() => {
    setProfileForm(initialProfileForm);
    setAvatarPreviewUrl(initialAvatarUrl);
    setSelectedAvatarFile(null);
    setLlmProfileContextUsesGeneratedDefault(initialLlmProfileContextUsesGeneratedDefault);
    if (avatarInputRef.current) {
      avatarInputRef.current.value = "";
    }
    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
  }, [initialAvatarUrl, initialLlmProfileContextUsesGeneratedDefault, initialProfileForm]);

  const handleProfileSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const formData = new FormData();
    formData.append("username", profileForm.username.trim());
    formData.append("email", profileForm.email.trim());
    formData.append("bio", profileForm.bio.trim());
    formData.append("llm_profile_context", profileForm.llmProfileContext.trim());
    if (selectedAvatarFile) {
      formData.append("avatar", selectedAvatarFile);
    }

    setProfileSaving(true);
    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/profile",
        {
          method: "POST",
          body: formData,
          credentials: "same-origin"
        },
        {
          defaultMessage: "更新失敗"
        }
      );

      const successMessage = asString(payload.message) || "プロフィールを更新しました";
      setProfileSaveStatus({ tone: "success", message: successMessage });
      setProfileSaveEffectToken((current) => current + 1);

      const persistedAvatarUrl = asString(payload.avatar_url) || avatarPreviewUrl;
      setAvatarPreviewUrl(persistedAvatarUrl || DEFAULT_AVATAR_URL);
      setInitialAvatarUrl(persistedAvatarUrl || DEFAULT_AVATAR_URL);

      const persistedProfile: ProfileFormState = {
        username: profileForm.username.trim(),
        email: profileForm.email.trim(),
        bio: profileForm.bio.trim(),
        llmProfileContext: profileForm.llmProfileContext.trim()
      };
      setProfileForm(persistedProfile);
      setInitialProfileForm(persistedProfile);
      setSelectedAvatarFile(null);
      setLlmProfileContextUsesGeneratedDefault(false);
      setInitialLlmProfileContextUsesGeneratedDefault(false);
      if (avatarInputRef.current) {
        avatarInputRef.current.value = "";
      }
    } catch (error) {
      setProfileSaveEffectActive(false);
      setProfileSaveStatus({
        tone: "error",
        message: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setProfileSaving(false);
    }
  }, [avatarPreviewUrl, profileForm, selectedAvatarFile]);

  const handleOpenPromptEdit = useCallback((prompt: PromptRecord) => {
    setEditPromptForm({
      id: asIdString(prompt.id),
      title: prompt.title,
      category: prompt.category,
      content: prompt.content,
      inputExamples: prompt.inputExamples,
      outputExamples: prompt.outputExamples
    });
  }, []);

  const handleDeletePrompt = useCallback(async (prompt: PromptRecord) => {
    const promptId = asIdString(prompt.id);
    if (!promptId) {
      alert("削除対象のプロンプトが見つかりませんでした。");
      return;
    }

    const confirmed = await showConfirmModal("このプロンプトを削除しますか？");
    if (!confirmed) {
      return;
    }

    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${promptId}`,
        {
          method: "DELETE",
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトの削除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      alert(response.message || "削除しました。");
      await loadMyPrompts();
    } catch (error) {
      alert(error instanceof Error ? error.message : "プロンプトの削除に失敗しました。");
    }
  }, [loadMyPrompts]);

  const handleEditPromptChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditPromptForm((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        [name]: value
      };
    });
  }, []);

  const handleEditPromptSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editPromptForm) {
      return;
    }

    if (!editPromptForm.id || !editPromptForm.title.trim() || !editPromptForm.category.trim() || !editPromptForm.content.trim()) {
      alert("編集フォームの値が不足しています。");
      return;
    }

    setPromptSaving(true);
    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${editPromptForm.id}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({
            title: editPromptForm.title,
            category: editPromptForm.category,
            content: editPromptForm.content,
            input_examples: editPromptForm.inputExamples,
            output_examples: editPromptForm.outputExamples
          })
        },
        {
          defaultMessage: "プロンプトの更新に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      alert(response.message || "更新しました。");
      setEditPromptForm(null);
      await loadMyPrompts();
    } catch (error) {
      alert(error instanceof Error ? error.message : "プロンプトの更新に失敗しました。");
    } finally {
      setPromptSaving(false);
    }
  }, [editPromptForm, loadMyPrompts]);

  const handleDeletePromptListEntry = useCallback(async (entry: PromptListEntry) => {
    const entryId = asIdString(entry.id);
    if (!entryId) {
      alert("削除対象のエントリが見つかりませんでした。");
      return;
    }

    const confirmed = await showConfirmModal("プロンプトリストから削除しますか？");
    if (!confirmed) {
      return;
    }

    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompt_list/${entryId}`,
        {
          method: "DELETE",
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトリストの削除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      alert(response.message || "プロンプトを削除しました。");
      await loadPromptList();
    } catch (error) {
      alert(error instanceof Error ? error.message : "プロンプトリストの削除に失敗しました。");
    }
  }, [loadPromptList]);

  const handleRegisterPasskey = useCallback(async () => {
    setRegisteringPasskey(true);
    try {
      await registerPasskey();
      alert("Passkeyを追加しました。");
      await loadPasskeys();
    } catch (error) {
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      alert(error instanceof Error ? error.message : "Passkey登録に失敗しました。");
    } finally {
      setRegisteringPasskey(false);
    }
  }, [loadPasskeys]);

  const handleDeletePasskey = useCallback(async (passkeyId: number) => {
    const confirmed = await showConfirmModal("このPasskeyを削除しますか？");
    if (!confirmed) {
      return;
    }

    setDeletingPasskeyId(passkeyId);
    try {
      await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/passkeys/delete",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ passkey_id: passkeyId }),
          credentials: "same-origin"
        },
        {
          defaultMessage: "Passkeyの削除に失敗しました。",
          hasApplicationError: (payload) => payload.status === "fail"
        }
      );
      await loadPasskeys();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Passkeyの削除に失敗しました。");
    } finally {
      setDeletingPasskeyId(null);
    }
  }, [loadPasskeys]);

  const myPromptCards = useMemo(
    () => myPrompts.map((prompt, index) => {
      const key = asIdString(prompt.id) || `${prompt.title}-${index}`;
      return (
        <PromptCard
          key={key}
          prompt={prompt}
          onEdit={handleOpenPromptEdit}
          onDelete={handleDeletePrompt}
        />
      );
    }),
    [handleDeletePrompt, handleOpenPromptEdit, myPrompts]
  );

  const promptListCards = useMemo(
    () => promptListEntries.map((entry, index) => {
      const key = asIdString(entry.id) || `${entry.title}-${index}`;
      return (
        <PromptListCard
          key={key}
          entry={entry}
          onDelete={handleDeletePromptListEntry}
        />
      );
    }),
    [handleDeletePromptListEntry, promptListEntries]
  );

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>ユーザー設定</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
        <link
          href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
          rel="stylesheet"
        />
        <link rel="stylesheet" href="/static/css/pages/user_settings/index.css" />
      </Head>

      <div className="user-settings-page">
        <div className="user-settings-layout">
          <SettingsSidebar activeSection={activeSection} onSectionSelect={handleSectionSelect} />

          <main className="settings-content">
            <div className="mb-4">
              <button
                type="button"
                className="settings-back-btn"
                onClick={() => window.history.back()}
                data-tooltip="前の画面に戻る"
                data-tooltip-placement="bottom"
              >
                <i className="bi bi-arrow-left"></i>
              </button>
            </div>

            <div id="profile-section" className={`settings-section${isSectionActive("profile") ? " active" : ""}`}>
              <div className={`settings-card${profileSaveEffectActive ? " settings-card--save-success" : ""}`}>
                <h2>ユーザープロフィール設定</h2>
                {profileSaveStatus ? (
                  <p
                    key={`${profileSaveStatus.tone}-${profileSaveEffectToken}`}
                    className={`settings-inline-feedback settings-inline-feedback--${profileSaveStatus.tone}${profileSaveStatus.tone === "success" && profileSaveEffectActive ? " settings-inline-feedback--celebrate" : ""}`}
                    role={profileSaveStatus.tone === "error" ? "alert" : "status"}
                    aria-live={profileSaveStatus.tone === "error" ? "assertive" : "polite"}
                  >
                    <i
                      className={`settings-inline-feedback__icon bi ${profileSaveStatus.tone === "success" ? "bi-check-circle-fill" : "bi-exclamation-circle-fill"}`}
                      aria-hidden="true"
                    ></i>
                    {profileSaveStatus.message}
                  </p>
                ) : null}
                <form id="userSettingsForm" onSubmit={handleProfileSubmit}>
                  <div className="form-group avatar-group">
                    <label className="form-label" htmlFor="avatarInput">
                      プロフィール画像
                    </label>
                    <div className="avatar-preview-wrapper">
                      <img
                        id="avatarPreview"
                        src={avatarPreviewUrl}
                        alt="Avatar Preview"
                        className="avatar-preview"
                      />
                      <button
                        type="button"
                        className="change-avatar-btn"
                        id="changeAvatarBtn"
                        data-tooltip="プロフィール画像を選択"
                        data-tooltip-placement="bottom"
                        onClick={() => avatarInputRef.current?.click()}
                      >
                        <i className="bi bi-pencil-fill"></i>
                      </button>
                    </div>
                    <input
                      ref={avatarInputRef}
                      type="file"
                      id="avatarInput"
                      accept="image/*"
                      hidden
                      onChange={handleAvatarFileChange}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="username">
                      ユーザー名
                    </label>
                    <input
                      type="text"
                      id="username"
                      name="username"
                      className="custom-form-control"
                      placeholder="ユーザー名を入力"
                      value={profileForm.username}
                      onChange={handleProfileInputChange}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="email">
                      メールアドレス
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      className="custom-form-control"
                      placeholder="example@domain.com"
                      value={profileForm.email}
                      onChange={handleProfileInputChange}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="bio">
                      自己紹介
                    </label>
                    <textarea
                      id="bio"
                      name="bio"
                      rows={4}
                      className="custom-form-control"
                      placeholder="自己紹介を入力 (例: 趣味、好きなことなど)"
                      value={profileForm.bio}
                      onChange={handleProfileInputChange}
                    ></textarea>
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="llmProfileContext">
                      AI に伝えておきたい情報
                    </label>
                    <textarea
                      id="llmProfileContext"
                      name="llmProfileContext"
                      rows={6}
                      className="custom-form-control"
                      placeholder={"例: 私の名前は山田太郎です。\nメールは taro@example.com です。\n普段は日本語で、結論から短く答えてください。"}
                      value={profileForm.llmProfileContext}
                      onChange={handleProfileInputChange}
                    ></textarea>
                    <p className="form-help-text">
                      未設定時はプロフィール情報が初期値として入ります。保存後は、この欄に残っている内容だけが AI に渡されます。
                    </p>
                  </div>

                  <div className="button-group">
                    <button type="button" className="secondary-button" id="cancelBtn" onClick={handleProfileCancel}>
                      キャンセル
                    </button>
                    <button
                      type="submit"
                      className={`primary-button profile-save-button${profileSaveEffectActive ? " profile-save-button--saved" : ""}`}
                      disabled={profileSaving}
                    >
                      <span className="profile-save-button__content">
                        {profileSaving ? <i className="bi bi-arrow-repeat" aria-hidden="true"></i> : null}
                        {!profileSaving && profileSaveEffectActive ? <i className="bi bi-check2-circle" aria-hidden="true"></i> : null}
                        {profileSaving ? "保存中..." : profileSaveEffectActive ? "保存しました" : "変更を保存"}
                      </span>
                    </button>
                  </div>
                </form>
              </div>
            </div>

            <div id="prompts-section" className={`settings-section${isSectionActive("prompts") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>プロンプト管理</h2>
                <div className="header-bar">
                  <h3 className="section-title">My Prompts</h3>
                </div>

                {myPromptsLoading ? <InlineLoading label="読み込み中..." className="mb-4" /> : null}
                {!myPromptsLoading && myPromptsError ? <p>{myPromptsError}</p> : null}
                {!myPromptsLoading && !myPromptsError && myPrompts.length === 0 ? <p>プロンプトが存在しません。</p> : null}

                <div id="promptList" className="prompt-grid">
                  {myPromptCards}
                </div>
              </div>
            </div>

            <div id="prompt-list-section" className={`settings-section${isSectionActive("prompt-list") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>プロンプトリスト</h2>
                <div className="header-bar">
                  <h3 className="section-title">Prompt List</h3>
                </div>

                {promptListLoading ? <InlineLoading label="読み込み中..." className="mb-4" /> : null}
                {!promptListLoading && promptListError ? <p>{promptListError}</p> : null}
                {!promptListLoading && !promptListError && promptListEntries.length === 0 ? (
                  <p>プロンプトリストは存在しません。</p>
                ) : null}

                <div id="promptListEntries" className="prompt-grid">
                  {promptListCards}
                </div>
              </div>
            </div>

            <div
              id="notifications-section"
              className={`settings-section${isSectionActive("notifications") ? " active" : ""}`}
            >
              <div className="settings-card">
                <h2>通知設定</h2>
                <p>通知設定機能は準備中です。</p>
              </div>
            </div>

            <div id="security-section" className={`settings-section${isSectionActive("security") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>セキュリティ</h2>

                <div className="security-stack">
                  <div className="security-panel">
                    <h3>Passkeys</h3>
                    <p id="passkeySupportStatus">{passkeySupportStatus}</p>
                    <div className="button-group">
                      <button
                        type="button"
                        className="primary-button"
                        id="registerPasskeyBtn"
                        disabled={!passkeySupported || registeringPasskey}
                        onClick={() => {
                          void handleRegisterPasskey();
                        }}
                      >
                        この端末にPasskeyを追加
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        id="refreshPasskeysBtn"
                        disabled={!passkeySupported || passkeysLoading}
                        onClick={() => {
                          void loadPasskeys();
                        }}
                      >
                        一覧を更新
                      </button>
                    </div>
                  </div>

                  <div className="security-panel">
                    <h3>登録済みPasskeys</h3>
                    <div id="passkeyList" className="passkey-list">
                      {passkeys.length === 0 ? (
                        <p className="passkey-empty">まだPasskeyは登録されていません。</p>
                      ) : (
                        passkeys.map((passkey) => (
                          <div key={passkey.id} className="passkey-item">
                            <div>
                              <strong>{passkey.label}</strong>
                              <div className="passkey-meta">
                                端末種別: {passkey.credentialDeviceType}
                                <br />
                                バックアップ: {passkey.credentialBackedUp ? "あり" : "なし"}
                                <br />
                                作成日時: {formatPasskeyDateTime(passkey.createdAt)}
                                <br />
                                最終利用: {formatPasskeyDateTime(passkey.lastUsedAt)}
                              </div>
                            </div>
                            <button
                              type="button"
                              className="secondary-button delete-passkey-btn"
                              data-passkey-id={String(passkey.id)}
                              disabled={deletingPasskeyId === passkey.id}
                              onClick={() => {
                                void handleDeletePasskey(passkey.id);
                              }}
                            >
                              削除
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>

        {editPromptForm ? (
          <EditPromptModal
            formState={editPromptForm}
            saving={promptSaving}
            onClose={() => {
              if (!promptSaving) {
                setEditPromptForm(null);
              }
            }}
            onChange={handleEditPromptChange}
            onSubmit={handleEditPromptSubmit}
          />
        ) : null}
      </div>
    </>
  );
}
