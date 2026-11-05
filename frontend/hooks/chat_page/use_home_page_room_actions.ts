// ホーム画面のチャットルーム操作（切り替え、新規作成と起動、メッセージ送信、削除・名称変更・ピン留め、複数選択）をまとめたフック。
// Hook bundling the home page chat room actions: switching, creating and launching, sending messages, deleting, renaming, pinning, and multi-select.
import {
  useCallback,
  useRef,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { KeyedMutator } from "swr";

import { CHAT_ROOMS_PAGE_SIZE, MAX_CHAT_MESSAGE_LENGTH, MAX_SETUP_INFO_LENGTH } from "../../lib/chat_page/constants";
import { hasImageAttachments, IMAGE_INPUT_MODEL_ONLY_MESSAGE, modelAcceptsImageInput } from "../../lib/chat_page/chat_images";
import {
  limitToFirstChatRoomsPage,
  removeChatRoomsById,
  setChatRoomPinnedAt,
  updateChatRoomTitle,
} from "../../lib/chat_page/home_page_controller_utils";
import { moveFocusOutOfHiddenRegion } from "../../lib/chat_page/focus_management";
import type { AttachedFile, ChatRoom, ChatRoomMode, ChatRoomsPage, NormalizedTask, UiChatMessage } from "../../lib/chat_page/types";
import { showConfirmModal, showPromptModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { scheduleSetupViewportFit } from "../../scripts/setup/setup_viewport";
import { useTranslation } from "../../contexts/locale_context";
import type { PinChatRoomRequest } from "../../types/generated/api_schemas";

// チャット起動時の遷移アニメーションを最低限見せるための待ち時間（ミリ秒）。ルーム作成が速くても画面が一瞬で切り替わらないようにする。
// Minimum time (ms) the launch transition stays visible, so the screen does not flip instantly even when room creation is fast.
const CHAT_LAUNCH_MIN_TRANSITION_MS = 420;
function waitForDuration(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

type ShareStatus = {
  message: string;
  error: boolean;
};

type PageViewState = "setup" | "chat" | "launching";

type UseHomePageRoomActionsParams = {
  cachedChatRooms?: ChatRoom[];
  chatInput: string;
  chatRooms: ChatRoom[];
  closeOverlaySidebar: () => void;
  openOverlaySidebar: () => void;
  closeShareModal: () => void;
  createNewChatRoom: (
    roomId: string,
    title: string,
    mode: ChatRoomMode,
    projectId?: number | null,
  ) => Promise<void>;
  currentRoomIdRef: MutableRefObject<string | null>;
  fetchChatRoomsPage: (url: string) => Promise<ChatRoomsPage>;
  editAndRegenerateMessage: (newMessage: string, trailingUserCount: number, model: string, roomId: string) => Promise<void>;
  attachedFiles: AttachedFile[];
  setAttachedFiles: Dispatch<SetStateAction<AttachedFile[]>>;
  generateResponse: (
    message: string,
    model: string,
    roomId: string,
    attachedFiles?: AttachedFile[],
    roomMode?: ChatRoomMode,
    options?: { unsentInputText?: string },
  ) => Promise<boolean>;
  regenerateLastResponse: (model: string, roomId: string) => Promise<void>;
  switchBranch: (messageId: number, roomId: string) => Promise<void>;
  isGenerating: boolean;
  isTaskOrderEditing: boolean;
  loadChatHistory: (roomId: string, shouldCheckGeneration?: boolean) => Promise<void>;
  loadLocalChatHistory: (roomId: string) => void;
  loggedIn: boolean;
  mutateChatRooms: KeyedMutator<ChatRoomsPage>;
  pageViewState: PageViewState;
  // 表示中のメッセージが 1 件以上あるか（メッセージは常に現在のルームのもの）。
  // Whether any message is currently loaded (messages always belong to the current room).
  hasMessages: boolean;
  persistCurrentRoomId: (roomId: string | null, mode?: ChatRoomMode) => void;
  prepareChatViewTransition: () => void;
  removeStoredHistory: (roomId: string) => void;
  selectedModel: string;
  setupInfo: string;
  stopGeneration: () => Promise<void>;
  taskLaunchInProgressRef: MutableRefObject<boolean>;
  temporaryModeEnabled: boolean;
  setTemporaryModeEnabled: Dispatch<SetStateAction<boolean>>;
  personalKnowledgeEnabled: boolean;
  setPersonalKnowledgeEnabled: Dispatch<SetStateAction<boolean>>;
  sharedPromptsEnabled: boolean;
  setSharedPromptsEnabled: Dispatch<SetStateAction<boolean>>;
  selectedRoomIds: Set<string>;
  setChatInput: Dispatch<SetStateAction<string>>;
  setChatRooms: Dispatch<SetStateAction<ChatRoom[]>>;
  setChatRoomsHasMore: Dispatch<SetStateAction<boolean>>;
  setChatRoomsNextCursor: Dispatch<SetStateAction<string | null>>;
  setCurrentRoomMode: Dispatch<SetStateAction<ChatRoomMode>>;
  setHistoryHasMore: Dispatch<SetStateAction<boolean>>;
  setIsBulkDeletingRooms: Dispatch<SetStateAction<boolean>>;
  setChatMessageListResetKey: Dispatch<SetStateAction<number>>;
  setHistoryNextBeforeId: Dispatch<SetStateAction<number | null>>;
  setIsLoadingOlder: Dispatch<SetStateAction<boolean>>;
  setIsRoomSelectionMode: Dispatch<SetStateAction<boolean>>;
  setLaunchingTaskName: Dispatch<SetStateAction<string | null>>;
  setLaunchingTaskId: Dispatch<SetStateAction<number | null>>;
  setMessages: Dispatch<SetStateAction<UiChatMessage[]>>;
  setOpenRoomActionsFor: Dispatch<SetStateAction<string | null>>;
  setPageViewState: Dispatch<SetStateAction<PageViewState>>;
  setSelectedRoomIds: Dispatch<SetStateAction<Set<string>>>;
  setSetupInfo: Dispatch<SetStateAction<string>>;
  setShareStatus: (status: ShareStatus) => void;
  setShareUrl: Dispatch<SetStateAction<string>>;
  resetChatRoomsPaginationWindow: () => void;
  // 「このプロジェクトで新規チャット」用。作成時に参照し、作成後にクリアする。
  // For "new chat in this project": read at creation time and cleared afterward.
  pendingProjectIdRef: MutableRefObject<number | null>;
  clearPendingProject: () => void;
};

// 状態は呼び出し元（use_home_page_controller）が持ち、このフックは API 呼び出しと、その結果を反映する状態更新だけを担当する。
// State is owned by the caller (use_home_page_controller); this hook only performs API calls and applies their results to that state.
export function useHomePageRoomActions({
  attachedFiles,
  setAttachedFiles,
  cachedChatRooms,
  chatInput,
  chatRooms,
  closeOverlaySidebar,
  openOverlaySidebar,
  closeShareModal,
  createNewChatRoom,
  currentRoomIdRef,
  editAndRegenerateMessage,
  fetchChatRoomsPage,
  generateResponse,
  regenerateLastResponse,
  switchBranch,
  isGenerating,
  isTaskOrderEditing,
  loadChatHistory,
  loadLocalChatHistory,
  loggedIn,
  mutateChatRooms,
  pageViewState,
  hasMessages,
  persistCurrentRoomId,
  prepareChatViewTransition,
  removeStoredHistory,
  selectedModel,
  setupInfo,
  stopGeneration,
  taskLaunchInProgressRef,
  temporaryModeEnabled,
  setTemporaryModeEnabled,
  personalKnowledgeEnabled,
  setPersonalKnowledgeEnabled,
  sharedPromptsEnabled,
  setSharedPromptsEnabled,
  selectedRoomIds,
  setChatInput,
  setChatRooms,
  setChatRoomsHasMore,
  setChatRoomsNextCursor,
  setCurrentRoomMode,
  setHistoryHasMore,
  setIsBulkDeletingRooms,
  setChatMessageListResetKey,
  setHistoryNextBeforeId,
  setIsLoadingOlder,
  setIsRoomSelectionMode,
  setLaunchingTaskName,
  setLaunchingTaskId,
  setMessages,
  setOpenRoomActionsFor,
  setPageViewState,
  setSelectedRoomIds,
  setSetupInfo,
  setShareStatus,
  setShareUrl,
  resetChatRoomsPaginationWindow,
  pendingProjectIdRef,
  clearPendingProject,
}: UseHomePageRoomActionsParams) {
  const { locale } = useTranslation();
  // コールバックの依存配列を増やさずに最新のロケールを参照するための ref。localize がこれを読む。
  // Ref so callbacks can read the latest locale without growing their dependency arrays; localize reads it.
  const localeRef = useRef(locale);
  localeRef.current = locale;
  const localize = useCallback((ja: string, en: string) => localeRef.current === "en" ? en : ja, []);
  // 画像を付けたまま画像を読めないモデルへ切り替えた場合は、送る前に止めて案内する。
  // Stop and explain before sending when images stay attached after switching to a model that cannot read them.
  const blocksImagesForSelectedModel = useCallback((): boolean => {
    if (modelAcceptsImageInput(selectedModel) || !hasImageAttachments(attachedFiles)) return false;
    showToast(
      localize(
        IMAGE_INPUT_MODEL_ONLY_MESSAGE,
        "Only GPT-6 Luna can read images. Switch the model to GPT-6 Luna or remove the images.",
      ),
      { variant: "error" },
    );
    return true;
  }, [attachedFiles, localize, selectedModel]);
  // handleAccessChat の多重実行を防ぐフラグ。
  // Guard flag that prevents handleAccessChat from running concurrently.
  const accessChatInProgressRef = useRef(false);
  // 削除処理は確認モーダルと通信を挟むため、コールバック生成時ではなく実行時の
  // 表示状態を見る必要がある。
  // Deletion awaits a confirm modal and a request, so it must read the view state
  // at call time rather than the one captured when the callback was created.
  const pageViewStateRef = useRef(pageViewState);
  pageViewStateRef.current = pageViewState;

  // メモ／共有プロンプト参照は「そのルームを作った時点のON/OFF」をルームIDごとに
  // 覚えておくための対応表。会話中に変更するUIが無いため、作成時の値がそのルーム
  // の値であり続ける。永続化はしない（temporaryModeEnabled と同じ理由）ので、
  // リロードすれば全ルームぶん消える。
  // A per-room record of "on/off at the moment this room was created" for the memo
  // and shared-prompt lookups. There is no UI to change either toggle once inside a
  // room's conversation, so the value at creation time is the room's value for good.
  // Not persisted, for the same reason as temporaryModeEnabled: a reload clears it
  // for every room.
  const roomReferenceTogglesRef = useRef<Map<string, { personalKnowledge: boolean; sharedPrompts: boolean }>>(
    new Map(),
  );

  const rememberRoomReferenceToggles = useCallback(
    (roomId: string) => {
      roomReferenceTogglesRef.current.set(roomId, {
        personalKnowledge: personalKnowledgeEnabled,
        sharedPrompts: sharedPromptsEnabled,
      });
    },
    [personalKnowledgeEnabled, sharedPromptsEnabled],
  );

  const restoreRoomReferenceToggles = useCallback(
    (roomId: string | null) => {
      const saved = roomId ? roomReferenceTogglesRef.current.get(roomId) : undefined;
      setPersonalKnowledgeEnabled(saved?.personalKnowledge ?? false);
      setSharedPromptsEnabled(saved?.sharedPrompts ?? false);
    },
    [setPersonalKnowledgeEnabled, setSharedPromptsEnabled],
  );

  const forgetRoomReferenceToggles = useCallback((roomId: string) => {
    roomReferenceTogglesRef.current.delete(roomId);
  }, []);

  const buildChatRoomsPageUrl = useCallback(() => {
    const params = new URLSearchParams({
      limit: String(CHAT_ROOMS_PAGE_SIZE),
    });
    return `/api/get_chat_rooms?${params.toString()}`;
  }, []);

  const resetChatMessageList = useCallback(() => {
    setChatMessageListResetKey((previous) => previous + 1);
  }, [setChatMessageListResetKey]);

  const showSetupForm = useCallback(() => {
    // 戻るボタンを含むチャット領域を隠す前にフォーカスを外す。
    // Blur focus before hiding the chat container from assistive technologies.
    moveFocusOutOfHiddenRegion(document.getElementById("chat-container"));
    setPageViewState("setup");
    closeOverlaySidebar();
    setLaunchingTaskName(null);
    setLaunchingTaskId(null);
    setSetupInfo("");
    // 未保存モードは一度の実行につき1回限りの指定にする。戻ってきたら
    // チェックを外し、次回の送信を通常モードに戻す。
    // Temporary mode is a one-shot toggle: clear it on return so the next
    // send defaults back to normal mode.
    setTemporaryModeEnabled(false);
    // メモ／共有プロンプト参照も同じ理由でセットアップ画面に戻るたびOFFへ戻す。
    // 次に送る発話は新しいルームになるため、前のルームの設定を引き継がせない。
    // The memo / shared-prompt toggles reset for the same reason: the next message
    // starts a new room, so the previous room's setting must not carry over to it.
    setPersonalKnowledgeEnabled(false);
    setSharedPromptsEnabled(false);
    closeShareModal();
    scheduleSetupViewportFit();
  }, [
    closeOverlaySidebar,
    closeShareModal,
    setLaunchingTaskId,
    setLaunchingTaskName,
    setPageViewState,
    setPersonalKnowledgeEnabled,
    setSharedPromptsEnabled,
    setTemporaryModeEnabled,
  ]);

  const clearCurrentRoomAfterDelete = useCallback(() => {
    resetChatMessageList();
    persistCurrentRoomId(null);
    setCurrentRoomMode("normal");
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: localize("共有するチャットルームを選択してください。", "Select a chat to share."), error: false });
    closeShareModal();
    // 開いているルームを削除したら、そのチャット画面には留まれないのでトップページへ戻す。
    // 既にトップページにいる場合は入力中の内容を消さないよう何もしない。
    // Deleting the room that is currently open leaves nothing to show, so go back to
    // the top page. When already there, stay put so a draft in the setup form survives.
    if (pageViewStateRef.current !== "setup") {
      showSetupForm();
    }
  }, [
    closeShareModal,
    persistCurrentRoomId,
    resetChatMessageList,
    setCurrentRoomMode,
    setMessages,
    setShareStatus,
    setShareUrl,
    showSetupForm,
  ]);

  const cancelRoomSelection = useCallback(() => {
    setIsRoomSelectionMode(false);
    setSelectedRoomIds(new Set());
    setOpenRoomActionsFor(null);
  }, [setIsRoomSelectionMode, setOpenRoomActionsFor, setSelectedRoomIds]);

  const enterRoomSelectionMode = useCallback(
    (initialRoomId?: string) => {
      setIsRoomSelectionMode(true);
      setSelectedRoomIds(new Set(initialRoomId ? [initialRoomId] : []));
      setOpenRoomActionsFor(null);
    },
    [setIsRoomSelectionMode, setOpenRoomActionsFor, setSelectedRoomIds],
  );

  const toggleRoomSelection = useCallback(
    (roomId: string) => {
      setSelectedRoomIds((previous) => {
        const next = new Set(previous);
        if (next.has(roomId)) {
          next.delete(roomId);
        } else {
          next.add(roomId);
        }
        return next;
      });
    },
    [setSelectedRoomIds],
  );

  // ログイン中は SWR の再検証結果、未ログインは直接取得した最初のページでルーム一覧を更新する。失敗時はキャッシュ済みの一覧を返す。
  // Refreshes the room list from the SWR revalidation when logged in, or from a direct fetch of the first page otherwise. On failure it returns the cached list.
  const loadChatRooms = useCallback(async (): Promise<ChatRoom[]> => {
    try {
      resetChatRoomsPaginationWindow();
      const page = loggedIn
        ? (await mutateChatRooms()) ?? {
            rooms: cachedChatRooms ?? [],
            pagination: { hasMore: false, nextCursor: null },
          }
        : await fetchChatRoomsPage(buildChatRoomsPageUrl());
      const rooms = page.rooms;
      setChatRooms(rooms);
      setChatRoomsHasMore(page.pagination.hasMore);
      setChatRoomsNextCursor(page.pagination.nextCursor);

      const activeRoomId = currentRoomIdRef.current;
      if (activeRoomId) {
        const activeRoom = rooms.find((room) => room.id === activeRoomId);
        if (activeRoom) {
          setCurrentRoomMode(activeRoom.mode);
        }
      }
      return rooms;
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
      return cachedChatRooms ?? [];
    }
  }, [
    buildChatRoomsPageUrl,
    cachedChatRooms,
    currentRoomIdRef,
    fetchChatRoomsPage,
    loggedIn,
    mutateChatRooms,
    resetChatRoomsPaginationWindow,
    setChatRooms,
    setChatRoomsHasMore,
    setChatRoomsNextCursor,
    setCurrentRoomMode,
  ]);

  // 作成直後のルームをサーバー応答を待たずに先頭へ追加する（楽観的更新）。一時チャットは一覧に出さないので対象外。
  // Adds the just-created room to the top of the list without waiting for the server (optimistic update). Temporary chats are not listed, so they are skipped.
  const upsertCreatedChatRoom = useCallback(
    (roomId: string, title: string, mode: ChatRoomMode) => {
      if (!loggedIn || mode !== "normal") return;

      const createdRoom: ChatRoom = {
        id: roomId,
        title: title.trim() || localize("新規チャット", "New chat"),
        createdAt: new Date().toISOString(),
        mode,
      };
      const upsert = (rooms: ChatRoom[] = []) => [
        createdRoom,
        ...rooms.filter((room) => room.id !== roomId),
      ];

      setChatRooms((previous) => upsert(previous));
      void mutateChatRooms(
        (previous) => {
          const previousRooms = previous?.rooms ?? cachedChatRooms ?? chatRooms;
          const nextRooms = limitToFirstChatRoomsPage(upsert(previousRooms));
          return {
            rooms: nextRooms,
            pagination: {
              hasMore: previous?.pagination.hasMore === true,
              nextCursor: previous?.pagination.nextCursor ?? null,
            },
          };
        },
        { revalidate: false },
      );
      void mutateChatRooms();
    },
    [
      cachedChatRooms,
      chatRooms,
      loggedIn,
      mutateChatRooms,
      setChatRooms,
    ],
  );

  // 別のルームを開く。ローカルに保存済みの履歴を先に表示し、続けてサーバーの履歴を読み込む。
  // Opens another room: shows the locally stored history first, then loads the server history.
  const switchChatRoom = useCallback(
    (roomId: string, roomMode?: ChatRoomMode, options?: { forceReload?: boolean }) => {
      const forceReload = options?.forceReload === true;
      if (pageViewState !== "chat") {
        prepareChatViewTransition();
      }

      // 開こうとしているルームを既に表示しているなら読み込み直さない。ただしトップページでは、
      // 再読み込みや別ページから戻った後に前回のルーム ID だけが復元され、会話はまだ読み込まれて
      // いないことがある。その状態で読み込みを省くと、会話があるのに空のチャット画面になる。
      // Skip reloading when this room is already on screen. On the top page, though, a reload or a
      // return from another page restores only the last room's id without its messages; skipping
      // the load there would open an empty chat screen for a room that does have a conversation.
      const roomAlreadyLoaded = pageViewState !== "setup" || hasMessages;
      if (currentRoomIdRef.current === roomId && !forceReload && roomAlreadyLoaded) {
        setPageViewState("chat");
        closeOverlaySidebar();
        setOpenRoomActionsFor(null);
        return;
      }

      resetChatMessageList();
      const nextRoom = chatRooms.find((room) => room.id === roomId);
      if (currentRoomIdRef.current !== roomId) {
        persistCurrentRoomId(roomId, roomMode ?? nextRoom?.mode);
      }
      // このルームが作られた時点のメモ／共有プロンプト参照設定を復元する。
      // 記録が無い（この機能導入前に作られた等の）ルームはOFFから始める。
      // Restore the memo / shared-prompt settings this room was created with.
      // A room with no record (created before this feature, for example) starts OFF.
      restoreRoomReferenceToggles(roomId);
      setCurrentRoomMode(roomMode ?? nextRoom?.mode ?? "normal");
      setPageViewState("chat");
      closeOverlaySidebar();
      setOpenRoomActionsFor(null);
      setShareStatus({ message: localize("共有リンクを準備しています...", "Preparing share link…"), error: false });
      setShareUrl("");
      loadLocalChatHistory(roomId);
      void loadChatHistory(roomId, true);
    },
    [
      chatRooms,
      closeOverlaySidebar,
      currentRoomIdRef,
      hasMessages,
      loadChatHistory,
      loadLocalChatHistory,
      pageViewState,
      persistCurrentRoomId,
      prepareChatViewTransition,
      resetChatMessageList,
      restoreRoomReferenceToggles,
      setPageViewState,
    ],
  );

  // ホームの「すべて見る」「チャット履歴」から呼ばれる一覧への入口。直近（または表示中）のルームを
  // 開きつつ、オーバーレイ幅ではサイドバーも開いた状態で遷移し、ラベルどおり一覧が最初に見えるようにする。
  // Entry point to the room list from the home screen ("view all" / history icon). Opens the latest
  // (or current) room and, at overlay widths, arrives with the sidebar open so the list is visible first.
  const handleAccessChat = useCallback(async () => {
    if (accessChatInProgressRef.current) return;
    accessChatInProgressRef.current = true;

    try {
      const activeRoomId = currentRoomIdRef.current;
      const preferredLoadedRoom =
        activeRoomId ? chatRooms.find((room) => room.id === activeRoomId) ?? null : chatRooms[0] ?? null;

      if (preferredLoadedRoom) {
        switchChatRoom(preferredLoadedRoom.id, preferredLoadedRoom.mode, { forceReload: true });
        openOverlaySidebar();
        return;
      }

      prepareChatViewTransition();
      setPageViewState("chat");
      openOverlaySidebar();
      setOpenRoomActionsFor(null);
      resetChatMessageList();

      if (activeRoomId) {
        loadLocalChatHistory(activeRoomId);
      } else {
        setMessages([]);
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      }

      try {
        const rooms = await loadChatRooms();
        const preferredFetchedRoom =
          activeRoomId ? rooms.find((room) => room.id === activeRoomId) ?? null : rooms[0] ?? null;

        if (preferredFetchedRoom) {
          switchChatRoom(preferredFetchedRoom.id, preferredFetchedRoom.mode, { forceReload: true });
          openOverlaySidebar();
          return;
        }

        if (activeRoomId) {
          switchChatRoom(activeRoomId, "normal", { forceReload: true });
          openOverlaySidebar();
          return;
        }

        resetChatMessageList();
        setMessages([]);
        persistCurrentRoomId(null);
        setCurrentRoomMode("normal");
        setHistoryHasMore(false);
        setHistoryNextBeforeId(null);
        setIsLoadingOlder(false);
      } catch (error) {
        console.error("ルーム一覧取得失敗:", error);
        if (!activeRoomId) {
          resetChatMessageList();
          setMessages([]);
          persistCurrentRoomId(null);
          setCurrentRoomMode("normal");
          setHistoryHasMore(false);
          setHistoryNextBeforeId(null);
          setIsLoadingOlder(false);
        }
      }
    } finally {
      accessChatInProgressRef.current = false;
    }
  }, [
    chatRooms,
    currentRoomIdRef,
    loadChatRooms,
    loadLocalChatHistory,
    openOverlaySidebar,
    persistCurrentRoomId,
    prepareChatViewTransition,
    resetChatMessageList,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsLoadingOlder,
    setMessages,
    setOpenRoomActionsFor,
    setPageViewState,
    switchChatRoom,
  ]);

  // 通常の「新規チャット」。選択モードを解除し、現在のルームを外してセットアップ画面へ戻る。
  // Plain "new chat": leaves selection mode, detaches the current room, and returns to the setup screen.
  const handleNewChat = useCallback(() => {
    cancelRoomSelection();
    // 通常の「新規チャット」ではプロジェクト紐づけを解除する。プロジェクト内からの
    // 新規チャットは handleNewChat の後に setNewChatProject を呼んで再設定する。
    // A plain "new chat" clears project association; the in-project flow re-sets it
    // by calling setNewChatProject after handleNewChat.
    clearPendingProject();
    persistCurrentRoomId(null);
    setCurrentRoomMode("normal");
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: localize("共有するチャットルームを選択してください。", "Select a chat to share."), error: false });
    showSetupForm();
  }, [cancelRoomSelection, persistCurrentRoomId, showSetupForm]);

  // 新規ルームの起動直前に、画面とルーム状態を「起動中」へそろえる。
  // Aligns screen and room state to "launching" right before a new room is created.
  const resetLaunchingRoomState = useCallback((roomId: string, roomMode: ChatRoomMode) => {
    // 新規チャット起動では履歴アンカリングが不要なので、ChatMessageList を
    // remount させない（resetChatMessageList を呼ばない）。remount すると
    // 初回アンカリングの opacity:0 ベールが再点灯し、起動時に一覧領域が一瞬
    // 消えて見える原因になる。既存ルームへの切替時のみ switchChatRoom 側で
    // remount する。
    // When launching a new chat there is no history to anchor, so ChatMessageList is not
    // remounted (resetChatMessageList is not called). A remount would re-arm the opacity:0
    // veil of the initial anchoring and make the list area briefly disappear on launch.
    // The remount happens only in switchChatRoom when switching to an existing room.
    persistCurrentRoomId(roomId, roomMode);
    // 今の（セットアップ画面で選んだ）参照設定を、この新しいルームの値として記録する。
    // Record the reference toggles as currently set on the setup screen as this new room's value.
    rememberRoomReferenceToggles(roomId);
    setCurrentRoomMode(roomMode);
    setMessages([]);
    setChatInput("");
    setOpenRoomActionsFor(null);
    setShareUrl("");
    setShareStatus({ message: localize("共有リンクを準備しています...", "Preparing share link…"), error: false });
    setHistoryHasMore(false);
    setHistoryNextBeforeId(null);
    setIsLoadingOlder(false);
    closeOverlaySidebar();
    prepareChatViewTransition();
    setPageViewState("launching");
  }, [
    closeOverlaySidebar,
    persistCurrentRoomId,
    prepareChatViewTransition,
    rememberRoomReferenceToggles,
    setPageViewState,
  ]);

  // タスクカードから新規チャットを始める。状況入力か添付が無ければ送らず案内する。ルーム作成と最低遷移時間を並行して待ち、作成中にユーザーが別のルームへ移っていたら送信をやめる。
  // Starts a new chat from a task card. Without setup text or attachments it shows a hint instead. Room creation and the minimum transition time are awaited together; if the user moved to another room meanwhile, the send is dropped.
  const handleTaskCardLaunch = useCallback(
    async (task: NormalizedTask) => {
      if (isTaskOrderEditing) return;
      if (taskLaunchInProgressRef.current) return;
      if (blocksImagesForSelectedModel()) return;

      taskLaunchInProgressRef.current = true;
      setLaunchingTaskName(task.name);
      setLaunchingTaskId(task.task_id);

      const roomId = Date.now().toString();
      const roomMode: ChatRoomMode = temporaryModeEnabled ? "temporary" : "normal";
      // プロジェクト紐づけは通常ルームのみ（一時チャットは永続化しないため）。
      // Project association applies to normal rooms only (temporary chats are not persisted).
      const projectId = roomMode === "normal" ? pendingProjectIdRef.current : null;
      const currentSetupInfo = setupInfo.trim();
      if (!currentSetupInfo && attachedFiles.length === 0) {
        showToast(
          localize(
            "タスクを始める前に、目的・対象・条件などを入力してください。",
            "Before starting a task, enter its goal, subject, or key conditions.",
          ),
          { variant: "error" },
        );
        taskLaunchInProgressRef.current = false;
        setLaunchingTaskName(null);
        setLaunchingTaskId(null);
        return;
      }
      const roomTitle = (currentSetupInfo || localize("新規チャット", "New chat")).slice(0, 255);
      const taskHeader = [
        `【タスク】${task.name}`,
        task.task_id !== null ? `【タスクID】${task.task_id}` : "",
      ].filter(Boolean).join("\n");
      const firstMessage = currentSetupInfo
        ? `${taskHeader}\n【状況・作業環境】${currentSetupInfo}`
        : taskHeader;

      resetLaunchingRoomState(roomId, roomMode);

      try {
        await Promise.all([
          createNewChatRoom(roomId, roomTitle, roomMode, projectId),
          waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
        ]);
        clearPendingProject();
        if (currentRoomIdRef.current !== roomId) {
          setLaunchingTaskName(null);
          setLaunchingTaskId(null);
          return;
        }
        upsertCreatedChatRoom(roomId, roomTitle, roomMode);
        removeStoredHistory(roomId);
        const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
        setAttachedFiles([]);
        setSetupInfo("");
        const generationPromise = generateResponse(
          firstMessage,
          selectedModel,
          roomId,
          filesToSend,
          roomMode,
          // タスク見出しを含む整形済み本文ではなく、ユーザーが入力した状況説明を戻す。
          // Restore the situation the user typed, not the composed task header.
          { unsentInputText: currentSetupInfo },
        );
        setPageViewState("chat");
        setLaunchingTaskName(null);
        setLaunchingTaskId(null);

        const completed = await generationPromise;
        if (!completed && loggedIn && roomMode === "normal") {
          void loadChatRooms();
        }
      } catch (error) {
        setPageViewState("setup");
        setLaunchingTaskName(null);
        setLaunchingTaskId(null);
        setMessages([]);
        persistCurrentRoomId(null);
        setCurrentRoomMode("normal");
        showToast(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`, {
          variant: "error",
        });
      } finally {
        taskLaunchInProgressRef.current = false;
      }
    },
    [
      attachedFiles,
      blocksImagesForSelectedModel,
      closeOverlaySidebar,
      createNewChatRoom,
      generateResponse,
      isTaskOrderEditing,
      loadChatRooms,
      loggedIn,
      persistCurrentRoomId,
      prepareChatViewTransition,
      resetLaunchingRoomState,
      selectedModel,
      setAttachedFiles,
      setLaunchingTaskName,
      setLaunchingTaskId,
      setPageViewState,
      setSetupInfo,
      setupInfo,
      temporaryModeEnabled,
      upsertCreatedChatRoom,
    ],
  );

  // セットアップ画面の入力から新規チャットを始める（タスクカードを使わない版）。起動の流れは handleTaskCardLaunch と同じ。
  // Starts a new chat from the setup screen input (the variant without a task card). The launch flow matches handleTaskCardLaunch.
  const handleSetupSendMessage = useCallback(async () => {
    if (taskLaunchInProgressRef.current) return;

    const firstMessage = setupInfo.trim();
    if (!firstMessage) return;
    if (firstMessage.length > MAX_SETUP_INFO_LENGTH) return;
    if (blocksImagesForSelectedModel()) return;

    taskLaunchInProgressRef.current = true;

    const roomId = Date.now().toString();
    const roomMode: ChatRoomMode = temporaryModeEnabled ? "temporary" : "normal";
    // プロジェクト紐づけは通常ルームのみ（一時チャットは永続化しないため）。
    // Project association applies to normal rooms only (temporary chats are not persisted).
    const projectId = roomMode === "normal" ? pendingProjectIdRef.current : null;
    const roomTitle = firstMessage.slice(0, 255) || localize("新規チャット", "New chat");

    resetLaunchingRoomState(roomId, roomMode);

    try {
      await Promise.all([
        createNewChatRoom(roomId, roomTitle, roomMode, projectId),
        waitForDuration(CHAT_LAUNCH_MIN_TRANSITION_MS),
      ]);
      clearPendingProject();
      if (currentRoomIdRef.current !== roomId) {
        return;
      }
      upsertCreatedChatRoom(roomId, roomTitle, roomMode);
      removeStoredHistory(roomId);
      const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
      setAttachedFiles([]);
      setSetupInfo("");
      const generationPromise = generateResponse(
        firstMessage,
        selectedModel,
        roomId,
        filesToSend,
        roomMode,
        { unsentInputText: firstMessage },
      );
      setPageViewState("chat");

      const completed = await generationPromise;
      if (!completed && loggedIn && roomMode === "normal") {
        void loadChatRooms();
      }
    } catch (error) {
      setPageViewState("setup");
      setMessages([]);
      persistCurrentRoomId(null);
      setCurrentRoomMode("normal");
      showToast(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`, {
        variant: "error",
      });
    } finally {
      taskLaunchInProgressRef.current = false;
    }
  }, [
    attachedFiles,
    blocksImagesForSelectedModel,
    closeOverlaySidebar,
    createNewChatRoom,
    generateResponse,
    loadChatRooms,
    loggedIn,
    persistCurrentRoomId,
    prepareChatViewTransition,
    resetLaunchingRoomState,
    selectedModel,
    setAttachedFiles,
    setPageViewState,
    setSetupInfo,
    setupInfo,
    temporaryModeEnabled,
    upsertCreatedChatRoom,
  ]);

  // 生成中に呼ばれた場合は送信ではなく停止として動く。
  // When called during generation it acts as "stop" rather than "send".
  const handleSendMessage = useCallback((overrideMessage?: string) => {
    if (isGenerating) {
      void stopGeneration();
      return;
    }

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    const message = (overrideMessage !== undefined ? overrideMessage : chatInput).trim();
    if (!message) return;

    if (message.length > MAX_CHAT_MESSAGE_LENGTH) return;
    if (blocksImagesForSelectedModel()) return;

    const filesToSend = attachedFiles.length > 0 ? [...attachedFiles] : undefined;
    if (overrideMessage === undefined) {
      setChatInput("");
    }
    setAttachedFiles([]);
    void generateResponse(message, selectedModel, roomId, filesToSend, undefined, {
      unsentInputText: message,
    });
  }, [
    attachedFiles,
    blocksImagesForSelectedModel,
    chatInput,
    generateResponse,
    isGenerating,
    selectedModel,
    setAttachedFiles,
    stopGeneration,
  ]);

  const handleRegenerateMessage = useCallback(() => {
    if (isGenerating) return;

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    void regenerateLastResponse(selectedModel, roomId);
  }, [isGenerating, regenerateLastResponse, selectedModel]);

  const handleEditAndRegenerateMessage = useCallback(
    (newMessage: string, trailingUserCount: number) => {
      if (isGenerating) return;
      const roomId = currentRoomIdRef.current;
      if (!roomId) return;
      void editAndRegenerateMessage(newMessage, trailingUserCount, selectedModel, roomId);
    },
    [editAndRegenerateMessage, isGenerating, selectedModel],
  );

  const handleSwitchBranch = useCallback(
    (messageId: number) => {
      if (isGenerating) return;
      const roomId = currentRoomIdRef.current;
      if (!roomId) return;
      void switchBranch(messageId, roomId);
    },
    [isGenerating, switchBranch],
  );

  // Enterキーは送信専用にし、生成中は何もしない。handleSendMessage は生成中に
  // 停止として振る舞うため、Enterを二回連打すると2回目が回答生成の停止になってしまう。
  // 停止操作は送信ボタン（停止ボタン）だけに限定する。
  // Enter only ever sends and is ignored while a response is streaming. handleSendMessage
  // doubles as "stop" during generation, so a rapid second Enter would otherwise abort the
  // answer. Stopping stays exclusive to the send/stop button.
  const handleChatInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (event.nativeEvent.isComposing) return;
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      if (isGenerating) return;
      handleSendMessage();
    },
    [handleSendMessage, isGenerating],
  );

  // 削除は楽観的更新で、先に一覧から消して API を呼び、失敗したら元の一覧へ戻す。
  // Deletion is optimistic: remove from the list first, call the API, and restore the previous list on failure.
  const handleDeleteRoom = useCallback(
    async (roomId: string, roomTitle: string) => {
      const confirmed = await showConfirmModal(`「${roomTitle}」を削除しますか？`);
      if (!confirmed) return;

      const previousRooms = chatRooms;
      setOpenRoomActionsFor(null);
      setChatRooms((previous) => removeChatRoomsById(previous, [roomId]));
      void mutateChatRooms(
        (previous) =>
          previous
            ? {
                ...previous,
                rooms: removeChatRoomsById(previous.rooms, [roomId]),
              }
            : previous,
        { revalidate: false },
      );

      try {
        const response = await resilientFetch("/api/delete_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, localize("削除失敗", "Delete failed"), response.status));
        }

        if (roomId === currentRoomIdRef.current) {
          clearCurrentRoomAfterDelete();
        }
        removeStoredHistory(roomId);
        forgetRoomReferenceToggles(roomId);

        void mutateChatRooms();
      } catch (error) {
        setChatRooms(previousRooms);
        void mutateChatRooms(
          (previous) =>
            previous
              ? {
                  ...previous,
                  rooms: limitToFirstChatRoomsPage(previousRooms),
                }
              : previous,
          { revalidate: false },
        );
        showToast(`削除失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [
      chatRooms,
      clearCurrentRoomAfterDelete,
      currentRoomIdRef,
      forgetRoomReferenceToggles,
      mutateChatRooms,
      removeStoredHistory,
      setChatRooms,
      setOpenRoomActionsFor,
    ],
  );

  // 選択した複数ルームの一括削除。方式は handleDeleteRoom と同じ（楽観的更新、失敗時に復元）。
  // Bulk delete of the selected rooms, using the same optimistic update and rollback as handleDeleteRoom.
  const handleBulkDeleteRooms = useCallback(async () => {
    const roomIds = Array.from(selectedRoomIds);
    if (roomIds.length === 0) return;

    const confirmed = await showConfirmModal(`${roomIds.length}件のチャットを削除しますか？`);
    if (!confirmed) return;

    setIsBulkDeletingRooms(true);
    const previousRooms = chatRooms;
    setChatRooms((previous) => removeChatRoomsById(previous, roomIds));
    void mutateChatRooms(
      (previous) =>
        previous
          ? {
              ...previous,
              rooms: removeChatRoomsById(previous.rooms, roomIds),
            }
          : previous,
      { revalidate: false },
    );

    try {
      const response = await resilientFetch("/api/delete_chat_rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ room_ids: roomIds }),
      });
      const payload = await readJsonBodySafe(response);

      if (!response.ok) {
        throw new Error(extractApiErrorMessage(payload, localize("削除失敗", "Delete failed"), response.status));
      }

      if (currentRoomIdRef.current && selectedRoomIds.has(currentRoomIdRef.current)) {
        clearCurrentRoomAfterDelete();
      }
      roomIds.forEach((roomId) => {
        removeStoredHistory(roomId);
        forgetRoomReferenceToggles(roomId);
      });

      cancelRoomSelection();
      void mutateChatRooms();
      showToast(`${roomIds.length}件のチャットを削除しました。`, { variant: "success" });
    } catch (error) {
      setChatRooms(previousRooms);
      void mutateChatRooms(
        (previous) =>
          previous
            ? {
                ...previous,
                rooms: limitToFirstChatRoomsPage(previousRooms),
              }
            : previous,
        { revalidate: false },
      );
      showToast(`削除失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
    } finally {
      setIsBulkDeletingRooms(false);
    }
  }, [
    cancelRoomSelection,
    chatRooms,
    clearCurrentRoomAfterDelete,
    currentRoomIdRef,
    forgetRoomReferenceToggles,
    mutateChatRooms,
    removeStoredHistory,
    selectedRoomIds,
    setChatRooms,
    setIsBulkDeletingRooms,
  ]);

  const handleRenameRoom = useCallback(
    async (roomId: string, currentTitle: string) => {
      const nextTitle = await showPromptModal(localize("チャットルーム名", "Chat name"), {
        title: localize("チャット名を変更", "Rename chat"),
        defaultValue: currentTitle,
        confirmLabel: localize("変更", "Rename"),
      });
      const normalizedTitle = nextTitle?.trim();
      if (!normalizedTitle) return;

      const previousRooms = chatRooms;
      setOpenRoomActionsFor(null);
      setChatRooms((previous) => updateChatRoomTitle(previous, roomId, normalizedTitle));
      void mutateChatRooms(
        (previous) =>
          previous
            ? {
                ...previous,
                rooms: updateChatRoomTitle(previous.rooms, roomId, normalizedTitle),
              }
            : previous,
        { revalidate: false },
      );

      try {
        const response = await resilientFetch("/api/rename_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId, new_title: normalizedTitle }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, localize("名前変更失敗", "Rename failed"), response.status));
        }

        void mutateChatRooms();
      } catch (error) {
        setChatRooms(previousRooms);
        void mutateChatRooms(
          (previous) =>
            previous
              ? {
                  ...previous,
                  rooms: limitToFirstChatRoomsPage(previousRooms),
                }
              : previous,
          { revalidate: false },
        );
        showToast(`名前変更失敗: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [chatRooms, mutateChatRooms, setChatRooms, setOpenRoomActionsFor],
  );

  // ピン留めの付け外し。他の操作と違い楽観的更新はしない（並び順がサーバー側のピン留め日時で決まるため）。
  // Pin/unpin. Unlike the other actions it is not optimistic, because ordering depends on the pin time recorded by the server.
  const handleToggleRoomPin = useCallback(
    async (roomId: string, pinned: boolean) => {
      setOpenRoomActionsFor(null);
      const failureLabel = pinned
        ? localize("ピン留めに失敗しました", "Could not pin the chat")
        : localize("ピン留めの解除に失敗しました", "Could not unpin the chat");
      try {
        const body: PinChatRoomRequest = { room_id: roomId, pinned };
        const response = await resilientFetch("/api/pin_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(body),
        });
        const payload = await readJsonBodySafe(response);
        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, failureLabel, response.status));
        }
        // 並び順はサーバーが記録したピン留め日時で決めるため、応答を待ってから反映する。
        // The pin time recorded by the server orders the section, so apply the response rather than guessing.
        const rawPinnedAt = (payload as { pinned_at?: unknown } | null)?.pinned_at;
        const pinnedAt = typeof rawPinnedAt === "string" && rawPinnedAt ? rawPinnedAt : null;
        setChatRooms((previous) => setChatRoomPinnedAt(previous, roomId, pinnedAt));
        void mutateChatRooms(
          (previous) =>
            previous
              ? {
                  ...previous,
                  rooms: setChatRoomPinnedAt(previous.rooms, roomId, pinnedAt),
                }
              : previous,
          { revalidate: false },
        );
        // 付け外しのどちらでも最初のページを取り直し、キャッシュとページ境界をサーバーに合わせる。
        // 外したルームの最終的な位置もここで確定する。
        // Refetch after either change so the cached first page matches the server; this also
        // settles an unpinned room where the server's activity order puts it.
        void mutateChatRooms();
      } catch (error) {
        showToast(`${failureLabel}: ${error instanceof Error ? error.message : String(error)}`, { variant: "error" });
      }
    },
    [localize, mutateChatRooms, setChatRooms, setOpenRoomActionsFor],
  );

  return {
    loadChatRooms,
    switchChatRoom,
    showSetupForm,
    handleAccessChat,
    handleNewChat,
    handleTaskCardLaunch,
    handleSetupSendMessage,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditAndRegenerateMessage,
    handleSwitchBranch,
    handleChatInputKeyDown,
    handleDeleteRoom,
    handleBulkDeleteRooms,
    handleRenameRoom,
    handleToggleRoomPin,
    enterRoomSelectionMode,
    toggleRoomSelection,
    cancelRoomSelection,
  };
}
