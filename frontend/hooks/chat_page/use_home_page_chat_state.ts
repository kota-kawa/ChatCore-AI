import { useRef, useState } from "react";

import type { ChatRoom, UiChatMessage } from "../../lib/chat_page/types";

export function useHomePageChatState() {
  const [chatRooms, setChatRooms] = useState<ChatRoom[]>([]);
  const [currentRoomId, setCurrentRoomId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyNextBeforeId, setHistoryNextBeforeId] = useState<number | null>(null);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [openRoomActionsFor, setOpenRoomActionsFor] = useState<string | null>(null);

  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const currentRoomIdRef = useRef<string | null>(null);
  const streamLastEventIdByRoomRef = useRef<Map<string, number>>(new Map());
  const abortControllerRef = useRef<AbortController | null>(null);
  const messageSeqRef = useRef(0);
  const pendingAutoScrollRef = useRef(false);
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);

  return {
    chatRooms,
    setChatRooms,
    currentRoomId,
    setCurrentRoomId,
    messages,
    setMessages,
    chatInput,
    setChatInput,
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
    chatMessagesRef,
    currentRoomIdRef,
    streamLastEventIdByRoomRef,
    abortControllerRef,
    messageSeqRef,
    pendingAutoScrollRef,
    prependScrollRestoreRef,
  };
}
