import { memo } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { GenerativeUiArtifactStatusV1 } from "../../lib/chat_page/types";

// 生成UIを表示できなかったことを、理由コードとともに利用者へ伝える。
// 以前は Artifact を黙って落として本文だけを残していたため、「生成しました。」という
// 文だけが残り、失敗が成功に見えていた。
// Tells the user that a generated UI could not be shown, together with its reason code.
// Artifacts used to be dropped silently, leaving a sentence like "Created." behind and
// making a failure look like a success.
type GenerativeUiStatusNoticeProps = {
  status: GenerativeUiArtifactStatusV1;
};

function GenerativeUiStatusNoticeComponent({ status }: GenerativeUiStatusNoticeProps) {
  const { t } = useTranslation();

  return (
    <aside className="generative-ui-status" role="status" data-state={status.state}>
      <p className="generative-ui-status__title">{t("chat.generatedUiUnavailable")}</p>
      <p className="generative-ui-status__hint">{t("chat.generatedUiUnavailableHint")}</p>
      <code className="generative-ui-status__reason">{status.reasonCode}</code>
    </aside>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const GenerativeUiStatusNotice = memo(GenerativeUiStatusNoticeComponent);
GenerativeUiStatusNotice.displayName = "GenerativeUiStatusNotice";
