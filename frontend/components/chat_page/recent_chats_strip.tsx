import { useHomePageSetupChatContext, useHomePageUiContext } from "../../contexts/chat_page/home_page_context";
import { useTranslation } from "../../contexts/locale_context";
import { splitPinnedChatRooms } from "../../lib/chat_page/home_page_controller_utils";

// 1 行に収める件数。これ以上はサイドバーの一覧（「すべて見る」）に任せる。
// How many chips fit the single row; anything beyond goes to the sidebar list ("view all").
const RECENT_CHAT_LIMIT = 5;

// ホーム画面の入力欄直下に置く「最近のチャット」。直前の会話に 1 タップで戻る導線と、
// 一覧（サイドバー）への入口を兼ねる。ログイン済みでルームが 1 件以上あるときだけ描画する。
// The "recent chats" row under the home screen's composer: a one-tap way back into a recent
// conversation plus the entry to the full list (sidebar). Rendered only when logged in with rooms.
export function RecentChatsStrip() {
  const { t } = useTranslation();
  const { loggedIn } = useHomePageUiContext();
  const { chatRooms, switchChatRoom, handleAccessChat } = useHomePageSetupChatContext();

  if (!loggedIn || chatRooms.length === 0) return null;

  // サイドバーと同じ並び（ピン留めをピン留め日時順で先頭に、続いて最終更新順）にそろえる。
  // ピン留め直後は再取得まで配列の位置が変わらないため、配列順をそのまま使うと食い違う。
  // Match the sidebar's order (pinned rooms first by pin time, then by last activity). Right
  // after pinning, the array position does not change until the refetch, so raw order would differ.
  const { pinned, recent } = splitPinnedChatRooms(chatRooms);
  const rooms = [...pinned, ...recent].slice(0, RECENT_CHAT_LIMIT);

  return (
    <nav className="recent-chats" aria-label={t("home.recentChats")}>
      <span className="recent-chats__label" aria-hidden="true">{t("home.recentChatsShort")}</span>
      <ul className="recent-chats__list">
        {rooms.map((room) => {
          const title = room.title || t("chat.new");
          return (
            <li key={room.id} className="recent-chats__item">
              <button
                type="button"
                className="recent-chats__chip cc-press"
                title={title}
                onClick={() => switchChatRoom(room.id, room.mode)}
              >
                {room.pinnedAt && <i className="bi bi-pin-angle-fill recent-chats__pin" aria-hidden="true"></i>}
                <span className="recent-chats__chip-title">{title}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        className="recent-chats__all cc-press"
        onClick={() => {
          void handleAccessChat();
        }}
      >
        <span>{t("home.viewAllChats")}</span>
        <i className="bi bi-chevron-right" aria-hidden="true"></i>
      </button>
    </nav>
  );
}
