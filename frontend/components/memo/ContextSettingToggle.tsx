// 記憶の設定を 1 行のスイッチとして出す共通部品。記憶の画面（MyContextPanel）の「自動で記憶する」「回答に使う」が使う。
// Shared one-row switch for a memory setting; used by "remember automatically" and "use in answers" on the memory screen (MyContextPanel).
import { useState } from "react";
import useSWR from "swr";

import { useTranslation } from "../../contexts/locale_context";

type EnabledSetting = { enabled: boolean };

type ContextSettingToggleProps = {
  // SWR のキャッシュキー。設定ごとに別の値にする。
  // SWR cache key; one per setting.
  cacheKey: string;
  // 見出しの id。行（section）の aria-labelledby が指す。
  // Id of the heading that the row (section) points to with aria-labelledby.
  titleId: string;
  title: string;
  description: string;
  switchLabel: string;
  // 通信が失敗してメッセージが得られなかったときに出す文言。
  // Text shown when a request failed without a message.
  failureText: string;
  load: () => Promise<EnabledSetting>;
  update: (input: EnabledSetting) => Promise<EnabledSetting>;
};

// 設定を読み込んで ON/OFF を切り替える。更新後は返ってきた最新値でキャッシュを直接更新する（再取得はしない）。
// Loads a setting and toggles it; after an update the returned value goes straight into the cache without revalidating.
export function ContextSettingToggle({
  cacheKey,
  titleId,
  title,
  description,
  switchLabel,
  failureText,
  load,
  update,
}: ContextSettingToggleProps) {
  const { t } = useTranslation();
  const { data, error, isLoading, mutate } = useSWR(cacheKey, load, {
    revalidateOnFocus: false,
  });
  const [busy, setBusy] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const enabled = data?.enabled ?? false;

  const handleToggle = async () => {
    if (busy || isLoading) return;
    setBusy(true);
    setErrorText(null);
    try {
      const updated = await update({ enabled: !enabled });
      await mutate(updated, { revalidate: false });
    } catch (updateError) {
      setErrorText(updateError instanceof Error ? updateError.message : failureText);
    } finally {
      setBusy(false);
    }
  };

  const failure = errorText ?? (error ? (error instanceof Error ? error.message : failureText) : null);

  return (
    <>
      <section className="memo-context-setting" aria-labelledby={titleId}>
        <div className="memo-context-setting__copy">
          <strong id={titleId}>{title}</strong>
          <p>{description}</p>
        </div>
        <button
          type="button"
          className={`memo-context-setting__toggle${enabled ? " is-enabled" : ""}`}
          role="switch"
          aria-checked={enabled}
          aria-label={switchLabel}
          onClick={() => void handleToggle()}
          disabled={busy || isLoading || Boolean(error)}
        >
          <span aria-hidden="true" />
          <span className="sr-only">{enabled ? t("memo.active") : t("memo.disabled")}</span>
        </button>
      </section>
      {failure && (
        <div className="memo-flash memo-flash--error" role="alert">
          {failure}
        </div>
      )}
    </>
  );
}
