// ホーム画面のチャット関連の状態（ルーム一覧、メッセージ、入力、履歴のページング、各種 ref）を宣言して返す hook。操作の実装は持たず、use_home_page_controller.ts が受け取って各アクションへ渡す。
// Hook that declares and returns the home page's chat state (rooms, messages, input, history pagination, refs). It holds no behavior; use_home_page_controller.ts passes the values on to the actions.
import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { capUiChatMessages } from "../../lib/chat_page/message_window";
import type { AttachedFile, ChatRoom, ChatRoomMode, UiChatMessage } from "../../lib/chat_page/types";

/**
 * ホームページのチャット状態を管理するカスタムフック
 * Custom hook to manage the chat state of the home page
 */
export function useHomePageChatState() {
  const [chatRooms, setChatRooms] = useState<ChatRoom[]>([]);
  const [chatRoomsHasMore, setChatRoomsHasMore] = useState(false);
  const [chatRoomsNextCursor, setChatRoomsNextCursor] = useState<string | null>(null);
  const [isLoadingMoreChatRooms, setIsLoadingMoreChatRooms] = useState(false);
  const [currentRoomId, setCurrentRoomId] = useState<string | null>(null);
  const [currentRoomMode, setCurrentRoomMode] = useState<ChatRoomMode>("normal");
  const [messages, setRawMessages] = useState<UiChatMessage[]>([]);
  
  // メッセージのリストを更新し、上限数で切り詰める
  // Update the messages list and cap it at the maximum limit
  const setMessages = useCallback<Dispatch<SetStateAction<UiChatMessage[]>>>((nextMessages) => {
    setRawMessages((previous) => {
      // 関数で更新されるか、値で直接更新されるかを判定
      // Determine if updating via function or direct value
      const resolvedMessages =
        typeof nextMessages === "function"
          ? (nextMessages as (previousMessages: UiChatMessage[]) => UiChatMessage[])(previous)
          : nextMessages;
      return capUiChatMessages(resolvedMessages);
    });
  }, []);
  
  const [chatInput, setChatInput] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyNextBeforeId, setHistoryNextBeforeId] = useState<number | null>(null);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [openRoomActionsFor, setOpenRoomActionsFor] = useState<string | null>(null);
  const [isRoomSelectionMode, setIsRoomSelectionMode] = useState(false);
  const [selectedRoomIds, setSelectedRoomIds] = useState<Set<string>>(() => new Set());
  const [isBulkDeletingRooms, setIsBulkDeletingRooms] = useState(false);
  // 値を増やすとメッセージ一覧が作り直され、末尾アンカーなどのスクロール状態が初期化される
  // Incrementing this remounts the message list, resetting scroll state such as bottom anchoring
  const [chatMessageListResetKey, setChatMessageListResetKey] = useState(0);

  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  // 非同期処理の途中でも現在のルームを同期的に確認するための ref（state の currentRoomId と同期させる）
  // Ref to check the current room synchronously inside async work (kept in sync with the currentRoomId state)
  const currentRoomIdRef = useRef<string | null>(null);
  // ルームごとに、最後に受け取った生成ストリームのイベント ID。切断後に Last-Event-ID で続きから再接続するために使う
  // Per room, the last generation-stream event ID received; used as Last-Event-ID to resume after a disconnect
  const streamLastEventIdByRoomRef = useRef<Map<string, number>>(new Map());
  // 進行中の生成リクエストを中断するための AbortController
  // AbortController used to cancel the in-flight generation request
  const abortControllerRef = useRef<AbortController | null>(null);
  // メッセージの一意な ID を採番する連番
  // Sequence number used to mint unique message IDs
  const messageSeqRef = useRef(0);
  // 次の描画で最下部へスクロールする予約フラグ
  // Flag requesting a scroll to the bottom on the next render
  const pendingAutoScrollRef = useRef(false);
  // 古い履歴を先頭に足す前のスクロール高さと位置。足したあとに読んでいた位置へ戻すために使う
  // Scroll height and position before older history is prepended, so the reader's position can be restored afterwards
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);

  return {
    chatRooms,
    setChatRooms,
    chatRoomsHasMore,
    setChatRoomsHasMore,
    chatRoomsNextCursor,
    setChatRoomsNextCursor,
    isLoadingMoreChatRooms,
    setIsLoadingMoreChatRooms,
    currentRoomId,
    setCurrentRoomId,
    currentRoomMode,
    setCurrentRoomMode,
    messages,
    setMessages,
    chatInput,
    setChatInput,
    attachedFiles,
    setAttachedFiles,
    isGenerating,
    setIsGenerating,
    historyHasMore,
    setHistoryHasMore,
    historyNextBeforeId,
    setHistoryNextBeforeId,
    isLoadingOlder,
    setIsLoadingOlder,
    sidebarOpen,
    setSidebarOpen,
    openRoomActionsFor,
    setOpenRoomActionsFor,
    isRoomSelectionMode,
    setIsRoomSelectionMode,
    selectedRoomIds,
    setSelectedRoomIds,
    isBulkDeletingRooms,
    setIsBulkDeletingRooms,
    chatMessageListResetKey,
    setChatMessageListResetKey,
    chatMessagesRef,
    currentRoomIdRef,
    streamLastEventIdByRoomRef,
    abortControllerRef,
    messageSeqRef,
    pendingAutoScrollRef,
    prependScrollRestoreRef,
  };
}
