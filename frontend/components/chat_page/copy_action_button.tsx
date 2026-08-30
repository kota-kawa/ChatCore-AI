import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";

// コピーアクションボタンのprops型定義
// Props type definition for the copy action button
type CopyActionButtonProps = {
  getText: () => string;
};

// チャットメッセージ下部のコピーボタン。共通の CopyButton にチャット用のクラスとラベルを与えるだけ。
// The copy button under a chat message: just the shared CopyButton wired with the chat classes and labels.
export function CopyActionButton({ getText }: CopyActionButtonProps) {
  const { locale } = useTranslation();

  return (
    <CopyButton
      getText={getText}
      label={locale === "en" ? "Copy message" : "メッセージをコピー"}
      tooltip="data-tooltip"
      tooltipPlacement="top"
      className="copy-btn message-action-btn"
      successClassName="copy-btn--success"
      errorClassName="copy-btn--error"
    />
  );
}
