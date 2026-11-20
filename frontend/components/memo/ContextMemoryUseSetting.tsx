// 記憶の「記憶を回答に使う」設定のスイッチ。記憶の画面（MyContextPanel）に置かれる。保存するかは別の設定（ContextExtractionSetting）。
// Switch for the "use memory in answers" memory setting; placed on the memory screen (MyContextPanel). Whether memory is saved is a
// separate setting (ContextExtractionSetting).
import { useTranslation } from "../../contexts/locale_context";
import {
  loadContextMemoryUseSettings as defaultLoad,
  updateContextMemoryUseSettings as defaultUpdate,
} from "../../lib/memo/context_api";
import { ContextSettingToggle } from "./ContextSettingToggle";

// 通信関数の束。テストでは差し替えられるよう、props で上書きできる形にしている。
// Bundle of API functions; overridable through props so tests can swap them.
export type ContextMemoryUseApi = {
  load: typeof defaultLoad;
  update: typeof defaultUpdate;
};

type ContextMemoryUseSettingProps = {
  api?: Partial<ContextMemoryUseApi>;
};

export function ContextMemoryUseSetting({ api }: ContextMemoryUseSettingProps) {
  const { t } = useTranslation();
  return (
    <ContextSettingToggle
      cacheKey="context-memory-use-settings"
      titleId="context-memory-use-setting-title"
      title={t("memo.memoryUseSettingTitle")}
      description={t("memo.memoryUseSettingDescription")}
      switchLabel={t("memo.memoryUse")}
      failureText={t("memo.updateMemoryUseFailed")}
      load={api?.load ?? defaultLoad}
      update={api?.update ?? defaultUpdate}
    />
  );
}
