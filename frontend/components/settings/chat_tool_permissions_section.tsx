import { useCallback, useEffect, useState } from "react";

import { InlineLoading } from "../ui/inline_loading";
import { SettingsSectionHeader } from "./settings_sections";
import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";
import { loadToolAutoApprovals, revokeToolAutoApproval } from "../../scripts/user/settings/api";
import { showToast } from "../../scripts/core/toast";
import type { ToolAutoApprovalApi } from "../../types/generated/api_schemas";

const TOOL_LABEL_KEYS: Record<ToolAutoApprovalApi["tool_name"], MessageKey> = {
  memo_create: "settings.chatPermissionsTool.memo_create",
  memo_append: "settings.chatPermissionsTool.memo_append",
  memo_edit: "settings.chatPermissionsTool.memo_edit",
};

// 設定画面の「チャットの権限」。チャットで「常に承認」にしたツールを並べ、取り消せるようにする。
// 取り消すと次から実行前に承認カードが出る。セクションを開くたびに最新の一覧を読み直す。
// The settings "Chat permissions" section: lists the tools set to "always approve" in chat and lets
// the user revoke them, after which an approval card is shown again. It reloads on every open.
export function ChatToolPermissionsSection({ isActive }: { isActive: boolean }) {
  const { t, formatDate } = useTranslation();
  const [grants, setGrants] = useState<ToolAutoApprovalApi[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [revokingTool, setRevokingTool] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setFailed(false);
    try {
      setGrants(await loadToolAutoApprovals(t("settings.chatPermissionsLoadFailed")));
    } catch {
      setFailed(true);
    }
  }, [t]);

  useEffect(() => {
    if (isActive) void reload();
  }, [isActive, reload]);

  const revoke = useCallback(
    async (toolName: ToolAutoApprovalApi["tool_name"]) => {
      if (revokingTool) return;
      setRevokingTool(toolName);
      try {
        await revokeToolAutoApproval(toolName, t("settings.chatPermissionsRevokeFailed"));
        setGrants((current) => (current ?? []).filter((grant) => grant.tool_name !== toolName));
        showToast(t("settings.chatPermissionsRevoked"), { variant: "success" });
      } catch (error) {
        showToast(error instanceof Error ? error.message : t("settings.chatPermissionsRevokeFailed"), { variant: "error" });
      } finally {
        setRevokingTool(null);
      }
    },
    [revokingTool, t],
  );

  let body;
  if (failed) {
    body = (
      <div className="usage-settings__error" role="alert">
        <p>{t("settings.chatPermissionsLoadFailed")}</p>
        <button type="button" className="ghost-button" onClick={() => void reload()}>
          {t("common.retry")}
        </button>
      </div>
    );
  } else if (!grants) {
    body = <InlineLoading label={t("common.loading")} />;
  } else if (grants.length === 0) {
    body = (
      <div className="passkey-empty">
        <i className="bi bi-shield-check" aria-hidden="true"></i>
        <span>{t("settings.chatPermissionsEmpty")}</span>
      </div>
    );
  } else {
    body = (
      <ul className="passkey-list chat-permissions-list">
        {grants.map((grant) => {
          const label = t(TOOL_LABEL_KEYS[grant.tool_name]);
          const revokeText = revokingTool === grant.tool_name
            ? t("settings.chatPermissionsRevoking")
            : t("settings.chatPermissionsRevoke");
          return (
            <li key={grant.tool_name} className="passkey-item chat-permissions-item">
              <div className="passkey-item__body">
                <strong className="passkey-item__title">{label}</strong>
                <dl className="security-meta">
                  <div className="security-meta__row">
                    <dt>{t("settings.chatPermissionsGrantedAt")}</dt>
                    <dd>{formatDate(grant.created_at, { dateStyle: "medium", timeStyle: "short" })}</dd>
                  </div>
                </dl>
              </div>
              <button
                type="button"
                className="secondary-button chat-permissions-item__revoke"
                disabled={revokingTool !== null}
                aria-label={`${label}: ${revokeText}`}
                onClick={() => void revoke(grant.tool_name)}
              >
                {revokeText}
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section id="chat-permissions-section" className={`settings-section${isActive ? " active" : ""}`}>
      <SettingsSectionHeader title={t("settings.chatPermissions")} lead={t("settings.chatPermissionsLead")} />
      <div className="settings-card" aria-live="polite" aria-busy={grants === null && !failed}>
        {body}
      </div>
    </section>
  );
}
