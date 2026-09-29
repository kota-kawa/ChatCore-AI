import { memo } from "react";

import { useTranslation } from "../../../contexts/locale_context";
import type { MessageKey } from "../../../lib/i18n/catalogs/ja";
import type { ToolApprovalApi } from "../../../types/generated/api_schemas";
import { ExpandableText, PreviewField } from "./shared";

type AnyPreview = NonNullable<ToolApprovalApi["preview"]>;
type ProfileSettingsPreview = Extract<AnyPreview, { kind: "profile_settings_update" }>;
type PreferredLocale = NonNullable<ProfileSettingsPreview["preferred_locale"]>;
type ProfileTheme = NonNullable<ProfileSettingsPreview["theme"]>;

const PREFERRED_LOCALE_KEYS: Record<PreferredLocale, MessageKey> = {
  ja: "chat.toolApproval.preview.locale.ja",
  en: "chat.toolApproval.preview.locale.en",
};

const PROFILE_THEME_KEYS: Record<ProfileTheme, MessageKey> = {
  light: "chat.toolApproval.preview.theme.light",
  dark: "chat.toolApproval.preview.theme.dark",
  auto: "chat.toolApproval.preview.theme.auto",
};

function ProfileSettingsApprovalPreviewComponent({ preview }: { preview: ProfileSettingsPreview }) {
  const { t } = useTranslation();
  const hasChanges = preview.display_name !== null
    || preview.bio !== null
    || preview.llm_profile_context !== null
    || preview.preferred_locale !== null
    || preview.theme !== null;

  if (!hasChanges) return null;

  const showText = (value: string) => (
    value.length === 0
      ? t("chat.toolApproval.preview.emptyWillClear")
      : <ExpandableText text={value} />
  );

  return (
    <dl className="tool-approval-preview">
      {preview.display_name !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.displayName")}>
          {showText(preview.display_name)}
        </PreviewField>
      ) : null}
      {preview.bio !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.bio")}>
          {showText(preview.bio)}
        </PreviewField>
      ) : null}
      {preview.llm_profile_context !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.llmProfileContext")}>
          {showText(preview.llm_profile_context)}
        </PreviewField>
      ) : null}
      {preview.preferred_locale !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.preferredLocale")}>
          {t(PREFERRED_LOCALE_KEYS[preview.preferred_locale])}
        </PreviewField>
      ) : null}
      {preview.theme !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.theme")}>
          {t(PROFILE_THEME_KEYS[preview.theme])}
          <div>{t("chat.toolApproval.preview.themeStoredLocally")}</div>
        </PreviewField>
      ) : null}
    </dl>
  );
}

export const ProfileSettingsApprovalPreview = memo(ProfileSettingsApprovalPreviewComponent);
ProfileSettingsApprovalPreview.displayName = "ProfileSettingsApprovalPreview";
