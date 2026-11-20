// 記憶の「チャットから自動で記憶する」設定のスイッチ。記憶の画面（MyContextPanel）に置かれる。回答に使うかは別の設定（ContextMemoryUseSetting）。
// Switch for the "remember from chats automatically" memory setting; placed on the memory screen (MyContextPanel). Whether memory is
// used in answers is a separate setting (ContextMemoryUseSetting).
import { useTranslation } from "../../contexts/locale_context";
import {
  loadContextExtractionSettings as defaultLoad,
  updateContextExtractionSettings as defaultUpdate,
} from "../../lib/memo/context_api";
import { ContextSettingToggle } from "./ContextSettingToggle";

// 通信関数の束。テストでは差し替えられるよう、props で上書きできる形にしている。
// Bundle of API functions; overridable through props so tests can swap them.
export type ContextExtractionApi = {
  load: typeof defaultLoad;
  update: typeof defaultUpdate;
};

type ContextExtractionSettingProps = {
  api?: Partial<ContextExtractionApi>;
};

export function ContextExtractionSetting({ api }: ContextExtractionSettingProps) {
  const { t } = useTranslation();
  return (
    <ContextSettingToggle
      cacheKey="context-extraction-settings"
      titleId="context-extraction-setting-title"
      title={t("memo.extractionSettingTitle")}
      description={t("memo.extractionSettingDescription")}
      switchLabel={t("memo.autoExtraction")}
      failureText={t("memo.updateExtractionFailed")}
      load={api?.load ?? defaultLoad}
      update={api?.update ?? defaultUpdate}
    />
  );
}
