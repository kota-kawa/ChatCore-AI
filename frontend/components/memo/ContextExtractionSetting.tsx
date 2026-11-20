// 記憶の「チャットから自動で記憶する」設定のスイッチ。記憶の画面（MyContextPanel）に置かれる。
// Switch for the "remember from chats automatically" memory setting; placed on the memory screen (MyContextPanel).
import { useState } from "react";
import useSWR from "swr";

import { useTranslation } from "../../contexts/locale_context";
import {
  loadContextExtractionSettings as defaultLoad,
  updateContextExtractionSettings as defaultUpdate,
} from "../../lib/memo/context_api";

// 通信関数の束。テストでは差し替えられるよう、props で上書きできる形にしている。
// Bundle of API functions; overridable through props so tests can swap them.
export type ContextExtractionApi = {
  load: typeof defaultLoad;
  update: typeof defaultUpdate;
};

type ContextExtractionSettingProps = {
  api?: Partial<ContextExtractionApi>;
};

// 自動抽出の設定を読み込んで ON/OFF を切り替える。更新後は返ってきた最新値でキャッシュを直接更新する（再取得はしない）。
// Loads the auto-extraction setting and toggles it; after an update the returned value goes straight into the cache without revalidating.
export function ContextExtractionSetting({ api }: ContextExtractionSettingProps) {
  const { t } = useTranslation();
  const load = api?.load ?? defaultLoad;
  const update = api?.update ?? defaultUpdate;
  const { data, error, isLoading, mutate } = useSWR("context-extraction-settings", load, {
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
      setErrorText(updateError instanceof Error ? updateError.message : t("memo.updateExtractionFailed"));
    } finally {
      setBusy(false);
    }
  };

  const failure =
    errorText ?? (error ? (error instanceof Error ? error.message : t("memo.updateExtractionFailed")) : null);

  return (
    <>
      <section className="memo-context-extraction-setting" aria-labelledby="context-extraction-setting-title">
        <div className="memo-context-extraction-setting__copy">
          <strong id="context-extraction-setting-title">{t("memo.extractionSettingTitle")}</strong>
          <p>{t("memo.extractionSettingDescription")}</p>
        </div>
        <button
          type="button"
          className={`memo-context-extraction-setting__toggle${enabled ? " is-enabled" : ""}`}
          role="switch"
          aria-checked={enabled}
          aria-label={t("memo.autoExtraction")}
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
