// ユーザー設定ページ全体のエントリポイント — プロフィール・外観・プロンプト・セキュリティを一画面で管理する
// Entry point for the user settings page — manages profile, appearance, prompts, and security in a single view
import { SeoHead } from "../components/SeoHead";
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
import { showToast } from "../scripts/core/toast";
import { getStoredThemePreference, setThemePreference, type ThemePreference } from "../scripts/core/theme";
import { asId, asString } from "../lib/utils";
import { EditPromptModal } from "../components/settings/edit_prompt_modal";
import { LikedPromptCard, PromptCard } from "../components/settings/prompt_cards";
import {
  AppearanceSettingsSection,
  AuthoredPromptsSection,
  LikedPromptsSection,
  NotificationsSettingsSection,
  ProfileSettingsSection,
  SecuritySettingsSection
} from "../components/settings/settings_sections";
import { SettingsSidebar } from "../components/settings/settings_sidebar";
import {
  ACCOUNT_DELETE_CONFIRMATION_TEXT,
  DEFAULT_AVATAR_URL,
  PASSKEY_INITIAL_SUPPORT_TEXT,
  PROFILE_SAVE_EFFECT_DURATION_MS,
  SETTINGS_NAV_ITEMS
} from "../scripts/user/settings/constants";
import {
  issueMcpOAuthClient,
  loadMcpOAuthClients,
  loadMcpOAuthConnections as fetchMcpOAuthConnections,
  revokeMcpOAuthClient,
  revokeMcpOAuthConnection,
  settingsFetchJsonOrThrow
} from "../scripts/user/settings/api";
import type {
  EditPromptFormState,
  EmailChangeStage,
  PasskeyRecord,
  ProfileFormState,
  ProfileSaveStatus,
  SettingsSection
} from "../scripts/user/settings/page_types";
import {
  parseLikedPromptsResponse,
  parseMyPromptsResponse,
  parsePromptManageMutationResponse,
  type McpOAuthClient,
  type McpOAuthClientCredentials,
  type McpOAuthConnection,
  type LikedPrompt,
  type PromptRecord
} from "../scripts/user/settings/types";
import {
  buildDefaultLlmProfileContext,
  normalizePasskeyRecords
} from "../scripts/user/settings/utils";

// ユーザー設定ページのメインコンポーネント — すべての設定セクションを統括する
// Main component for the user settings page — orchestrates all settings sections
export default function UserSettingsPage() {
  // 現在表示中のセクションを管理する
  // Track which section is currently displayed
  const [activeSection, setActiveSection] = useState<SettingsSection>("profile");

  // プロフィールフォームの現在値と初期値を別々に保持して「キャンセル」で元に戻せるようにする
  // Keep current and initial profile form values separately so Cancel can restore them
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
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaveStatus, setProfileSaveStatus] = useState<ProfileSaveStatus | null>(null);
  // トークンをインクリメントすることで保存成功アニメーションを再トリガーする
  // Incrementing this token re-triggers the save-success animation effect
  const [profileSaveEffectToken, setProfileSaveEffectToken] = useState(0);
  const [profileSaveEffectActive, setProfileSaveEffectActive] = useState(false);
  // LLM コンテキストが自動生成のデフォルト値を使っているかどうかを追跡する
  // Track whether the LLM context is currently using the auto-generated default
  const [llmProfileContextUsesGeneratedDefault, setLlmProfileContextUsesGeneratedDefault] = useState(false);
  const [initialLlmProfileContextUsesGeneratedDefault, setInitialLlmProfileContextUsesGeneratedDefault] = useState(false);

  // 投稿済みプロンプト一覧の状態
  // State for the list of prompts authored by this user
  const [myPrompts, setMyPrompts] = useState<PromptRecord[]>([]);
  const [myPromptsLoading, setMyPromptsLoading] = useState(false);
  const [myPromptsError, setMyPromptsError] = useState<string | null>(null);

  // いいねしたプロンプト一覧の状態
  // State for the list of liked prompt entries
  const [likedPrompts, setLikedPrompts] = useState<LikedPrompt[]>([]);
  const [likedPromptsLoading, setLikedPromptsLoading] = useState(false);
  const [likedPromptsError, setLikedPromptsError] = useState<string | null>(null);

  // 編集モーダルの表示制御 — null のときモーダルは非表示
  // Controls the edit modal; null means the modal is hidden
  const [editPromptForm, setEditPromptForm] = useState<EditPromptFormState | null>(null);
  const [promptSaving, setPromptSaving] = useState(false);

  const [themePreference, setThemePreferenceState] = useState<ThemePreference>("auto");

  // Passkey 関連の状態 — 対応有無・一覧・ローディング・操作中フラグを管理する
  // Passkey-related state — tracks support, list, loading, and in-progress operation flags
  const [passkeySupported, setPasskeySupported] = useState(true);
  const [passkeySupportStatus, setPasskeySupportStatus] = useState(PASSKEY_INITIAL_SUPPORT_TEXT);
  const [passkeys, setPasskeys] = useState<PasskeyRecord[]>([]);
  const [passkeysLoading, setPasskeysLoading] = useState(false);
  const [registeringPasskey, setRegisteringPasskey] = useState(false);
  const [deletingPasskeyId, setDeletingPasskeyId] = useState<number | null>(null);
  const [mcpOAuthConnections, setMcpOAuthConnections] = useState<McpOAuthConnection[]>([]);
  const [mcpOAuthConnectionsLoading, setMcpOAuthConnectionsLoading] = useState(false);
  const [deletingMcpOAuthConnectionId, setDeletingMcpOAuthConnectionId] = useState<string | null>(null);
  const [mcpOAuthClients, setMcpOAuthClients] = useState<McpOAuthClient[]>([]);
  const [mcpOAuthClientsLoading, setMcpOAuthClientsLoading] = useState(false);
  const [mcpOAuthClientIssuing, setMcpOAuthClientIssuing] = useState(false);
  const [mcpOAuthClientLabel, setMcpOAuthClientLabel] = useState("");
  const [mcpOAuthClientRedirectUri, setMcpOAuthClientRedirectUri] = useState("");
  const [deletingMcpOAuthClientId, setDeletingMcpOAuthClientId] = useState<string | null>(null);
  const [mcpOAuthClientCredentials, setMcpOAuthClientCredentials] = useState<McpOAuthClientCredentials | null>(null);
  const [accountDeleteConfirmation, setAccountDeleteConfirmation] = useState("");
  const [accountDeleting, setAccountDeleting] = useState(false);
  const [accountDeleteError, setAccountDeleteError] = useState<string | null>(null);

  // メールアドレス変更フローの状態 — 段階・入力値・送信中フラグ・結果を管理する
  // Email-change flow state — tracks stage, input values, submission flag, and result
  const [emailChangeStage, setEmailChangeStage] = useState<EmailChangeStage>("idle");
  const [emailChangeNewEmail, setEmailChangeNewEmail] = useState("");
  const [emailChangeCode, setEmailChangeCode] = useState("");
  const [emailChangeSubmitting, setEmailChangeSubmitting] = useState(false);
  const [emailChangeStatus, setEmailChangeStatus] = useState<ProfileSaveStatus | null>(null);

  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  // 保存成功アニメーション用タイマーを保持し、再保存時にリセットできるようにする
  // Holds the save-effect timer so it can be cleared and reset on rapid saves
  const profileSaveEffectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 現在のセクションが指定したセクションかどうかを返すコールバック
  // Callback that returns whether the given section is currently active
  const isSectionActive = useCallback(
    (section: SettingsSection) => activeSection === section,
    [activeSection]
  );

  // プロフィール情報を API から取得してフォームに反映する
  // Fetch profile data from the API and populate the form
  const loadProfile = useCallback(async () => {
    setProfileLoading(true);
    try {
      const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
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
      // llm_profile_context が null/undefined の場合はプロフィールから自動生成する
      // Auto-generate LLM context from profile fields when llm_profile_context is null/undefined
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
    } finally {
      setProfileLoading(false);
    }
  }, []);

  // ユーザーが投稿したプロンプト一覧を取得する
  // Fetch the list of prompts authored by the current user
  const loadMyPrompts = useCallback(async () => {
    setMyPromptsLoading(true);
    setMyPromptsError(null);

    try {
      const { payload } = await settingsFetchJsonOrThrow(
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

  // ユーザーがいいねしたプロンプト一覧を取得する
  // Fetch the list of prompts liked by the current user
  const loadLikedPrompts = useCallback(async () => {
    setLikedPromptsLoading(true);
    setLikedPromptsError(null);
    try {
      const { payload } = await settingsFetchJsonOrThrow(
        "/prompt_manage/api/liked_prompts",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "いいねしたプロンプトの取得に失敗しました。"
        }
      );
      setLikedPrompts(parseLikedPromptsResponse(payload));
    } catch (error) {
      setLikedPrompts([]);
      setLikedPromptsError(error instanceof Error ? error.message : "いいねしたプロンプトの取得に失敗しました。");
    } finally {
      setLikedPromptsLoading(false);
    }
  }, []);

  // ブラウザの Passkey 対応を確認してから登録済み Passkey 一覧を取得する
  // Check browser passkey support, then fetch the list of registered passkeys
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
      const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
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
      showToast(error instanceof Error ? error.message : "Passkey一覧の取得に失敗しました。", { variant: "error" });
    } finally {
      setPasskeysLoading(false);
    }
  }, []);

  // 外部AIサービスへ許可した MCP 連携を取得する
  // Fetch the MCP connections authorized for external AI services.
  const loadMcpOAuthConnectionList = useCallback(async () => {
    setMcpOAuthConnectionsLoading(true);
    try {
      setMcpOAuthConnections(await fetchMcpOAuthConnections());
    } catch (error) {
      setMcpOAuthConnections([]);
      showToast(
        error instanceof Error ? error.message : "AIサービス連携一覧の取得に失敗しました。",
        { variant: "error" }
      );
    } finally {
      setMcpOAuthConnectionsLoading(false);
    }
  }, []);

  const loadMcpOAuthClientList = useCallback(async () => {
    setMcpOAuthClientsLoading(true);
    try {
      const result = await loadMcpOAuthClients();
      setMcpOAuthClients(result.clients);
      setMcpOAuthClientRedirectUri((current) => current || result.default_redirect_uri);
    } catch (error) {
      setMcpOAuthClients([]);
      showToast(
        error instanceof Error ? error.message : "連携用認証情報の取得に失敗しました。",
        { variant: "error" }
      );
    } finally {
      setMcpOAuthClientsLoading(false);
    }
  }, []);

  // マウント時にページクラスを追加し、テーマ・プロフィール・Passkey を初期ロードする
  // On mount, add the page class and perform initial loads for theme, profile, and passkeys
  useEffect(() => {
    document.body.classList.add("settings-page");

    setThemePreferenceState(getStoredThemePreference());

    const importCustomElements = async () => {
      await import("../scripts/components/popup_menu");
    };
    void importCustomElements();

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

  // 保存成功トークンが変わるたびにアニメーションを一定時間表示して自動消灯する
  // Show the save-success animation for a fixed duration each time the token increments
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

  // 編集モーダルが開いている間、Escape キーでモーダルを閉じられるようにする
  // While the edit modal is open, allow closing it with the Escape key
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

  // モーダルの開閉に合わせて body に modal-open クラスを付け外しし、背景スクロールを制御する
  // Toggle modal-open on body to prevent background scrolling when the modal is shown
  useEffect(() => {
    document.body.classList.toggle("modal-open", Boolean(editPromptForm));
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [editPromptForm]);

  // セクション切り替え時に必要なデータを遅延ロードする
  // Lazily load section-specific data when the user navigates to that section
  const handleSectionSelect = useCallback((section: SettingsSection) => {
    setActiveSection(section);

    if (section === "prompts") {
      void loadMyPrompts();
      return;
    }
    if (section === "liked-prompts") {
      void loadLikedPrompts();
      return;
    }
    if (section === "security") {
      void loadPasskeys();
      void loadMcpOAuthConnectionList();
      void loadMcpOAuthClientList();
    }
  }, [loadMcpOAuthClientList, loadLikedPrompts, loadMcpOAuthConnectionList, loadMyPrompts, loadPasskeys]);

  // 共有URLやブラウザ再読み込みから目的の設定へ直接移動できるよう、section クエリを初回表示へ反映する
  // Apply the section query on first load so shared URLs and reloads open the intended settings area directly
  useEffect(() => {
    const requestedSection = new URLSearchParams(window.location.search).get("section");
    const isKnownSection = SETTINGS_NAV_ITEMS.some((item) => item.section === requestedSection);
    if (isKnownSection) {
      handleSectionSelect(requestedSection as SettingsSection);
    }
  }, [handleSectionSelect]);

  // テーマ選択を React 状態と localStorage の両方に反映する
  // Apply the selected theme to both React state and localStorage
  const handleThemeSelect = useCallback((preference: ThemePreference) => {
    setThemePreferenceState(preference);
    setThemePreference(preference);
  }, []);

  // プロフィールフィールドの変更を処理する — LLM コンテキストが自動生成の場合は連動更新する
  // Handle profile field changes — auto-update LLM context when it uses the generated default
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

        // LLM コンテキスト欄自体を編集したら「自動生成を使用中」フラグを解除する
        // When the LLM context field itself is edited, stop using the auto-generated default
        if (name === "llmProfileContext") {
          setLlmProfileContextUsesGeneratedDefault(false);
          return nextProfile;
        }

        // 他のフィールドが変わったとき、自動生成中なら LLM コンテキストも再生成する
        // When other fields change and auto-default is active, regenerate the LLM context
        if (llmProfileContextUsesGeneratedDefault) {
          nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
        }
        return nextProfile;
      });
    },
    [llmProfileContextUsesGeneratedDefault]
  );

  // アバター画像ファイルを選択し、FileReader でプレビュー表示する
  // Select an avatar image file and display a preview using FileReader
  const handleAvatarFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    if (!file) {
      return;
    }
    // 画像以外のファイルは無視してアップロードを防ぐ
    // Ignore non-image files to prevent uploading unsupported types
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

  // プロフィール変更をキャンセルして初期値に戻す
  // Cancel profile changes and restore the initial values
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

  // プロフィールフォームを送信し、成功時に初期値を更新して「変更なし」状態にする
  // Submit the profile form and update the initial values on success to reset dirty state
  const handleProfileSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    // multipart/form-data でアバターファイルも一緒に送信するため FormData を使う
    // Use FormData to include the avatar file in a multipart/form-data POST
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
      const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
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
      // トークンをインクリメントして保存成功アニメーションを再起動する
      // Increment the token to restart the save-success animation
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

  // メールアドレス変更が完了したとき、フォームと初期値の両方に新しいアドレスを反映する
  // After an email change is committed, apply the new address to both form state and initial state
  const applyCommittedEmail = useCallback((email: string) => {
    setProfileForm((prev) => {
      const nextProfile = { ...prev, email };
      if (llmProfileContextUsesGeneratedDefault) {
        nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
      }
      return nextProfile;
    });
    setInitialProfileForm((prev) => {
      const nextProfile = { ...prev, email };
      if (initialLlmProfileContextUsesGeneratedDefault) {
        nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
      }
      return nextProfile;
    });
  }, [initialLlmProfileContextUsesGeneratedDefault, llmProfileContextUsesGeneratedDefault]);

  // メールアドレス変更の第 1 ステップ — 新しいアドレスへの確認コード送信をリクエストする
  // First step of the email-change flow — request a verification code sent to the new address
  const handleRequestEmailChange = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextEmail = emailChangeNewEmail.trim();
    if (!nextEmail) {
      setEmailChangeStatus({ tone: "error", message: "新しいメールアドレスを入力してください。" });
      return;
    }

    setEmailChangeSubmitting(true);
    setEmailChangeStatus(null);
    try {
      await settingsFetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/email/request_change",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ new_email: nextEmail })
        },
        { defaultMessage: "確認メールの送信に失敗しました。" }
      );
      // 現在のメールへの確認コード入力ステージに進む
      // Advance to the stage that collects the verification code sent to the current email
      setEmailChangeStage("current_email");
      setEmailChangeCode("");
      setEmailChangeStatus({
        tone: "success",
        message: "現在のメールアドレスに確認コードを送信しました。"
      });
    } catch (error) {
      setEmailChangeStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "確認メールの送信に失敗しました。"
      });
    } finally {
      setEmailChangeSubmitting(false);
    }
  }, [emailChangeNewEmail]);

  // メールアドレス変更の第 2・第 3 ステップ — 確認コードを検証して変更を完了させる
  // Second and third steps — verify the confirmation code and finalize the email change
  const handleConfirmEmailChange = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const authCode = emailChangeCode.trim();
    if (!authCode) {
      setEmailChangeStatus({ tone: "error", message: "確認コードを入力してください。" });
      return;
    }

    setEmailChangeSubmitting(true);
    setEmailChangeStatus(null);
    try {
      const { payload } = await settingsFetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/email/confirm_change",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ auth_code: authCode })
        },
        { defaultMessage: "確認コードの検証に失敗しました。" }
      );

      const committedEmail = asString(payload.email);
      // email が返ってきた場合は変更完了 — フォームを初期化してアイドル状態に戻す
      // If an email is returned, the change is complete — reset and return to idle state
      if (committedEmail) {
        applyCommittedEmail(committedEmail);
        setEmailChangeNewEmail("");
        setEmailChangeCode("");
        setEmailChangeStage("idle");
        setEmailChangeStatus({
          tone: "success",
          message: "メールアドレスを変更しました。"
        });
        return;
      }

      // stage が new_email であれば新しいメールへのコード確認ステップに進む
      // If stage is new_email, advance to confirming the code sent to the new address
      if (asString(payload.stage) === "new_email") {
        setEmailChangeStage("new_email");
        setEmailChangeCode("");
        setEmailChangeStatus({
          tone: "success",
          message: "新しいメールアドレスに確認コードを送信しました。"
        });
        return;
      }

      setEmailChangeStatus({
        tone: "success",
        message: asString(payload.message) || "確認しました。"
      });
    } catch (error) {
      setEmailChangeStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "確認コードの検証に失敗しました。"
      });
    } finally {
      setEmailChangeSubmitting(false);
    }
  }, [applyCommittedEmail, emailChangeCode]);

  // メールアドレス変更フローを中断してアイドル状態に戻す
  // Abort the email-change flow and reset to idle state
  const handleCancelEmailChange = useCallback(() => {
    setEmailChangeStage("idle");
    setEmailChangeCode("");
    setEmailChangeStatus(null);
  }, []);

  // 編集モーダルを開き、対象プロンプトの現在値をフォームに設定する
  // Open the edit modal and populate the form with the selected prompt's current values
  const handleOpenPromptEdit = useCallback((prompt: PromptRecord) => {
    setEditPromptForm({
      id: asId(prompt.id),
      title: prompt.title,
      category: prompt.category,
      content: prompt.content,
      inputExamples: prompt.inputExamples,
      outputExamples: prompt.outputExamples
    });
  }, []);

  // 確認ダイアログを経てプロンプトを削除し、成功後に一覧を再取得する
  // Delete a prompt after user confirmation, then refresh the list on success
  const handleDeletePrompt = useCallback(async (prompt: PromptRecord) => {
    const promptId = asId(prompt.id);
    if (!promptId) {
      showToast("削除対象のプロンプトが見つかりませんでした。", { variant: "error" });
      return;
    }

    const confirmed = await showConfirmModal("このプロンプトを削除しますか？");
    if (!confirmed) {
      return;
    }

    const previousPrompts = myPrompts;
    setMyPrompts((current) => current.filter((entry) => asId(entry.id) !== promptId));

    try {
      const { payload } = await settingsFetchJsonOrThrow(
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
      showToast(response.message || "削除しました。", { variant: "success" });
      void loadMyPrompts();
    } catch (error) {
      setMyPrompts(previousPrompts);
      showToast(error instanceof Error ? error.message : "プロンプトの削除に失敗しました。", { variant: "error" });
    }
  }, [loadMyPrompts, myPrompts]);

  // プロンプト編集フォームの汎用入力変更ハンドラ
  // Generic input change handler for the prompt edit form
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

  // プロンプト編集フォームのカテゴリ変更ハンドラ
  // Handler for category changes in the prompt edit form
  const handleEditPromptCategoryChange = useCallback((value: string) => {
    setEditPromptForm((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        category: value
      };
    });
  }, []);

  // プロンプト編集フォームを送信して更新 API を呼び出す — 必須フィールドのバリデーションも行う
  // Submit the prompt edit form and call the update API — includes required-field validation
  const handleEditPromptSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editPromptForm) {
      return;
    }

    // 必須フィールドが揃っていない場合はサーバーに送らず早期リターンする
    // Guard against empty required fields before sending the request
    // カテゴリ未選択は空キーで表されるため、空判定だけで弾ける
    // An unselected category is the empty key, so the emptiness check alone rejects it
    if (
      !editPromptForm.id ||
      !editPromptForm.title.trim() ||
      !editPromptForm.category.trim() ||
      !editPromptForm.content.trim()
    ) {
      showToast("編集フォームの値が不足しています。", { variant: "error" });
      return;
    }

    const previousPrompts = myPrompts;
    const optimisticPrompt = {
      title: editPromptForm.title,
      category: editPromptForm.category,
      content: editPromptForm.content,
      inputExamples: editPromptForm.inputExamples,
      outputExamples: editPromptForm.outputExamples,
    };
    setMyPrompts((current) =>
      current.map((prompt) =>
        asId(prompt.id) === editPromptForm.id
          ? { ...prompt, ...optimisticPrompt }
          : prompt
      )
    );

    setPromptSaving(true);
    try {
      const { payload } = await settingsFetchJsonOrThrow(
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
      showToast(response.message || "更新しました。", { variant: "success" });
      setEditPromptForm(null);
      void loadMyPrompts();
    } catch (error) {
      setMyPrompts(previousPrompts);
      showToast(error instanceof Error ? error.message : "プロンプトの更新に失敗しました。", { variant: "error" });
    } finally {
      setPromptSaving(false);
    }
  }, [editPromptForm, loadMyPrompts, myPrompts]);

  // 確認ダイアログを経ていいねを解除する
  // Remove a liked prompt after user confirmation
  const handleUnlikePrompt = useCallback(async (entry: LikedPrompt) => {
    const promptId = asId(entry.promptId);
    if (!promptId) {
      showToast("いいね解除対象のプロンプトが見つかりませんでした。", { variant: "error" });
      return;
    }

    const confirmed = await showConfirmModal("このプロンプトのいいねを解除しますか？");
    if (!confirmed) {
      return;
    }

    const previousLikedPrompts = likedPrompts;
    setLikedPrompts((current) => current.filter((item) => asId(item.promptId) !== promptId));

    try {
      const { payload } = await settingsFetchJsonOrThrow(
        "/prompt_share/api/like",
        {
          method: "DELETE",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt_id: promptId })
        },
        {
          defaultMessage: "いいねの解除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "いいねを解除しました。", { variant: "success" });
    } catch (error) {
      setLikedPrompts(previousLikedPrompts);
      showToast(error instanceof Error ? error.message : "いいねの解除に失敗しました。", { variant: "error" });
    }
  }, [likedPrompts]);

  // ブラウザの Passkey 登録フローを起動し、キャンセル時はトーストを出さない
  // Launch the browser passkey registration flow; silently swallow user-cancelled errors
  const handleRegisterPasskey = useCallback(async () => {
    setRegisteringPasskey(true);
    try {
      await registerPasskey();
      showToast("Passkeyを追加しました。", { variant: "success" });
      await loadPasskeys();
    } catch (error) {
      // ユーザーが自らキャンセルした場合はエラートーストを表示しない
      // Do not show an error toast when the user intentionally cancelled the flow
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      showToast(error instanceof Error ? error.message : "Passkey登録に失敗しました。", { variant: "error" });
    } finally {
      setRegisteringPasskey(false);
    }
  }, [loadPasskeys]);

  // 確認ダイアログを経て指定の Passkey を削除する
  // Delete the specified passkey after user confirmation
  const handleDeletePasskey = useCallback(async (passkeyId: number) => {
    const confirmed = await showConfirmModal("このPasskeyを削除しますか？");
    if (!confirmed) {
      return;
    }

    setDeletingPasskeyId(passkeyId);
    try {
      await settingsFetchJsonOrThrow<Record<string, unknown>>(
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
      showToast(error instanceof Error ? error.message : "Passkeyの削除に失敗しました。", { variant: "error" });
    } finally {
      setDeletingPasskeyId(null);
    }
  }, [loadPasskeys]);

  // 指定したAIサービスのMCP認可を失効し、以後の投稿を停止する
  // Revoke an AI service's MCP authorization and prevent future publishing.
  const handleDeleteMcpOAuthConnection = useCallback(async (connection: McpOAuthConnection) => {
    const confirmed = await showConfirmModal(
      `「${connection.client_name}」からのAIサービス連携を解除しますか？`
    );
    if (!confirmed) {
      return;
    }

    setDeletingMcpOAuthConnectionId(connection.id);
    try {
      await revokeMcpOAuthConnection(connection.id);
      setMcpOAuthConnections((current) => current.filter((entry) => entry.id !== connection.id));
      showToast("AIサービス連携を解除しました。", { variant: "success" });
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "AIサービス連携の解除に失敗しました。",
        { variant: "error" }
      );
    } finally {
      setDeletingMcpOAuthConnectionId(null);
    }
  }, []);

  const handleIssueMcpOAuthClient = useCallback(async () => {
    setMcpOAuthClientIssuing(true);
    try {
      const credentials = await issueMcpOAuthClient(
        mcpOAuthClientLabel.trim(),
        mcpOAuthClientRedirectUri.trim()
      );
      setMcpOAuthClientCredentials(credentials);
      setMcpOAuthClients((current) => [
        {
          client_id: credentials.client_id,
          label: credentials.label,
          redirect_uri: credentials.redirect_uri,
          created_at: new Date().toISOString()
        },
        ...current
      ]);
      setMcpOAuthClientLabel("");
      showToast("連携用認証情報を発行しました。シークレットをコピーしてください。", { variant: "success" });
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "連携用認証情報の発行に失敗しました。",
        { variant: "error" }
      );
    } finally {
      setMcpOAuthClientIssuing(false);
    }
  }, [mcpOAuthClientLabel, mcpOAuthClientRedirectUri]);

  const handleDeleteMcpOAuthClient = useCallback(async (client: McpOAuthClient) => {
    const name = client.label || client.client_id;
    const confirmed = await showConfirmModal(
      `認証情報「${name}」を削除しますか？この認証情報で確立済みの接続もすぐに使えなくなります。`
    );
    if (!confirmed) {
      return;
    }

    setDeletingMcpOAuthClientId(client.client_id);
    try {
      await revokeMcpOAuthClient(client.client_id);
      setMcpOAuthClients((current) => current.filter((entry) => entry.client_id !== client.client_id));
      setMcpOAuthClientCredentials((current) =>
        current && current.client_id === client.client_id ? null : current
      );
      // 認証情報を削除すると接続も切れるため、接続一覧を更新して反映する。
      // Deleting a credential severs its connections, so refresh the connection list.
      void loadMcpOAuthConnectionList();
      showToast("認証情報を削除しました。", { variant: "success" });
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "認証情報の削除に失敗しました。",
        { variant: "error" }
      );
    } finally {
      setDeletingMcpOAuthClientId(null);
    }
  }, [loadMcpOAuthConnectionList]);

  // アカウントを完全削除する — 確認テキスト入力と二段階ダイアログで誤操作を防ぐ
  // Permanently delete the account — guarded by typed confirmation and a two-step dialog
  const handleDeleteAccount = useCallback(async () => {
    const normalizedConfirmation = accountDeleteConfirmation.trim();
    // 入力テキストが正確に一致しない場合はボタンが無効になるが、防衛的にチェックする
    // Button is already disabled unless text matches, but check defensively
    if (normalizedConfirmation !== ACCOUNT_DELETE_CONFIRMATION_TEXT) {
      setAccountDeleteError(`確認のため「${ACCOUNT_DELETE_CONFIRMATION_TEXT}」と入力してください。`);
      return;
    }

    const confirmed = await showConfirmModal(
      "アカウントと保存済みデータを削除します。この操作は取り消せません。本当に削除しますか？"
    );
    if (!confirmed) {
      return;
    }

    setAccountDeleting(true);
    setAccountDeleteError(null);
    try {
      await settingsFetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/account",
        {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({ confirmation: normalizedConfirmation })
        },
        {
          defaultMessage: "アカウント削除に失敗しました。"
        }
      );
      showToast("アカウントを削除しました。", { variant: "success" });
      // 削除完了後、少し間を置いてからログインページへリダイレクトする
      // Brief delay before redirecting to login so the toast can be seen
      window.setTimeout(() => {
        window.location.assign("/login");
      }, 400);
    } catch (error) {
      setAccountDeleteError(error instanceof Error ? error.message : "アカウント削除に失敗しました。");
      setAccountDeleting(false);
    }
  }, [accountDeleteConfirmation]);

  // 投稿済みプロンプトのカードリストをメモ化して不要な再レンダリングを防ぐ
  // Memoize the authored prompt card list to avoid unnecessary re-renders
  const myPromptCards = useMemo(
    () => myPrompts.map((prompt, index) => {
      const key = asId(prompt.id) || `${prompt.title}-${index}`;
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

  // いいねしたプロンプトのカードリストをメモ化して不要な再レンダリングを防ぐ
  // Memoize the liked prompt card list to avoid unnecessary re-renders
  const likedPromptCards = useMemo(
    () => likedPrompts.map((entry, index) => {
      const key = asId(entry.id) || `${entry.title}-${index}`;
      return (
        <LikedPromptCard
          key={key}
          entry={entry}
          onDelete={handleUnlikePrompt}
        />
      );
    }),
    [handleUnlikePrompt, likedPrompts]
  );

  return (
    <>
      <SeoHead
        title="ユーザー設定 | Chat Core"
        description="Chat Coreのユーザー設定ページです。"
        canonicalPath="/settings"
        noindex
      >
        <link
          href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="user-settings-page">
        <action-menu></action-menu>

        <div className="user-settings-layout">
          {/* サイドバーでセクションを切り替え、コンテンツ側で対応パネルを表示する / Sidebar switches sections; the content area shows the corresponding panel */}
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

            <ProfileSettingsSection
              isActive={isSectionActive("profile")}
              profileSaveEffectActive={profileSaveEffectActive}
              profileSaveStatus={profileSaveStatus}
              profileSaveEffectToken={profileSaveEffectToken}
              profileLoading={profileLoading}
              profileForm={profileForm}
              avatarPreviewUrl={avatarPreviewUrl}
              avatarInputRef={avatarInputRef}
              profileSaving={profileSaving}
              onProfileSubmit={handleProfileSubmit}
              onAvatarFileChange={handleAvatarFileChange}
              onProfileInputChange={handleProfileInputChange}
              onProfileCancel={handleProfileCancel}
            />

            <AppearanceSettingsSection
              isActive={isSectionActive("appearance")}
              themePreference={themePreference}
              onThemeSelect={handleThemeSelect}
            />

            <AuthoredPromptsSection
              isActive={isSectionActive("prompts")}
              loading={myPromptsLoading}
              error={myPromptsError}
              promptCount={myPrompts.length}
              promptCards={myPromptCards}
            />

            <LikedPromptsSection
              isActive={isSectionActive("liked-prompts")}
              loading={likedPromptsLoading}
              error={likedPromptsError}
              promptCount={likedPrompts.length}
              promptCards={likedPromptCards}
            />

            <NotificationsSettingsSection isActive={isSectionActive("notifications")} />

            <SecuritySettingsSection
              isActive={isSectionActive("security")}
              profileEmail={profileForm.email}
              emailChangeStatus={emailChangeStatus}
              emailChangeStage={emailChangeStage}
              emailChangeNewEmail={emailChangeNewEmail}
              emailChangeCode={emailChangeCode}
              emailChangeSubmitting={emailChangeSubmitting}
              passkeySupportStatus={passkeySupportStatus}
              passkeySupported={passkeySupported}
              passkeys={passkeys}
              passkeysLoading={passkeysLoading}
              registeringPasskey={registeringPasskey}
              deletingPasskeyId={deletingPasskeyId}
              mcpOAuthConnections={mcpOAuthConnections}
              mcpOAuthConnectionsLoading={mcpOAuthConnectionsLoading}
              deletingMcpOAuthConnectionId={deletingMcpOAuthConnectionId}
              mcpOAuthClients={mcpOAuthClients}
              mcpOAuthClientsLoading={mcpOAuthClientsLoading}
              mcpOAuthClientIssuing={mcpOAuthClientIssuing}
              mcpOAuthClientLabel={mcpOAuthClientLabel}
              mcpOAuthClientRedirectUri={mcpOAuthClientRedirectUri}
              deletingMcpOAuthClientId={deletingMcpOAuthClientId}
              mcpOAuthClientCredentials={mcpOAuthClientCredentials}
              accountDeleteConfirmation={accountDeleteConfirmation}
              accountDeleting={accountDeleting}
              accountDeleteError={accountDeleteError}
              onRequestEmailChange={handleRequestEmailChange}
              onConfirmEmailChange={handleConfirmEmailChange}
              onCancelEmailChange={handleCancelEmailChange}
              onEmailChangeNewEmailChange={(value) => {
                setEmailChangeNewEmail(value);
                setEmailChangeStatus(null);
              }}
              onEmailChangeCodeChange={(value) => {
                setEmailChangeCode(value);
                setEmailChangeStatus(null);
              }}
              onRegisterPasskey={handleRegisterPasskey}
              onRefreshPasskeys={loadPasskeys}
              onDeletePasskey={handleDeletePasskey}
              onRefreshMcpOAuthConnections={loadMcpOAuthConnectionList}
              onDeleteMcpOAuthConnection={handleDeleteMcpOAuthConnection}
              onRefreshMcpOAuthClients={loadMcpOAuthClientList}
              onMcpOAuthClientLabelChange={setMcpOAuthClientLabel}
              onMcpOAuthClientRedirectUriChange={setMcpOAuthClientRedirectUri}
              onIssueMcpOAuthClient={handleIssueMcpOAuthClient}
              onDeleteMcpOAuthClient={handleDeleteMcpOAuthClient}
              onAccountDeleteConfirmationChange={(value) => {
                setAccountDeleteConfirmation(value);
                setAccountDeleteError(null);
              }}
              onDeleteAccount={handleDeleteAccount}
            />
          </main>
        </div>

        {/* プロンプト編集モーダル — editPromptForm が存在する場合のみレンダリングする / Prompt edit modal — rendered only when editPromptForm is non-null */}
        {editPromptForm ? (
          <EditPromptModal
            formState={editPromptForm}
            saving={promptSaving}
            onClose={() => {
              if (!promptSaving) {
                setEditPromptForm(null);
              }
            }}
            onCategoryChange={handleEditPromptCategoryChange}
            onChange={handleEditPromptChange}
            onSubmit={handleEditPromptSubmit}
          />
        ) : null}
      </div>
    </>
  );
}
