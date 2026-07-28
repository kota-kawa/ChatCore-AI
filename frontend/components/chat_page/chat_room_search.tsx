import { memo, type ChangeEvent } from "react";
import { useTranslation } from "../../contexts/locale_context";

// サイドバーのチャットルームをタイトルで絞り込む検索入力コンポーネント。
// Search input component for filtering chat rooms by title in the sidebar.
type ChatRoomSearchProps = {
  value: string;
  onChange: (value: string) => void;
  onClear: () => void;
};

function ChatRoomSearchComponent({ value, onChange, onClear }: ChatRoomSearchProps) {
  const { t, locale } = useTranslation();
  const hasQuery = value.length > 0;

  return (
    <div className="chat-room-search" role="search">
      <i className="bi bi-search chat-room-search__icon" aria-hidden="true"></i>
      <input
        type="search"
        className="chat-room-search__input"
        placeholder={t("chat.search")}
        aria-label={t("chat.search")}
        value={value}
        autoComplete="off"
        // ブラウザ標準の検索クリアボタンは見た目が不揃いなので独自ボタンに任せる。
        // Suppress the native clear control; a custom clear button is provided instead.
        onChange={(event: ChangeEvent<HTMLInputElement>) => {
          onChange(event.target.value);
        }}
      />
      {hasQuery && (
        <button
          type="button"
          className="chat-room-search__clear cc-press"
          aria-label={locale === "en" ? "Clear search" : "検索をクリア"}
          onClick={() => {
            onClear();
          }}
        >
          <i className="bi bi-x-lg" aria-hidden="true"></i>
        </button>
      )}
    </div>
  );
}

// 親の再レンダリングで無駄に再描画しないよう memo でラップする。
// Wrap in memo to avoid needless re-renders when the parent updates.
export const ChatRoomSearch = memo(ChatRoomSearchComponent);
ChatRoomSearch.displayName = "ChatRoomSearch";
