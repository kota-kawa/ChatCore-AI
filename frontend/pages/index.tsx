import Head from "next/head";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
} from "react";
import defaultTasks from "../data/default_tasks.json";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { CACHE_TTL_MS, STORAGE_KEYS, AUTH_SUCCESS_HINT } from "../scripts/core/constants";
import {
  extractApiErrorMessage,
  fetchJsonOrThrow,
  parseJsonText,
  readJsonBodySafe,
} from "../scripts/core/runtime_validation";
import { formatMultilineHtml } from "../scripts/core/html";
import { formatLLMOutput } from "../scripts/chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../scripts/chat/message_utils";
import { initPromptAssist } from "../scripts/components/prompt_assist";
import type { TaskItem } from "../scripts/setup/setup_types";
import {
  invalidateTasksCache,
  readCachedTasks,
  writeCachedTasks,
} from "../scripts/setup/setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "../scripts/setup/setup_viewport";

type NormalizedTask = {
  name: string;
  prompt_template: string;
  response_rules: string;
  output_skeleton: string;
  input_examples: string;
  output_examples: string;
  is_default: boolean;
};

type ChatRoom = {
  id: string;
  title: string;
  created_at?: string;
};

type ChatSender = "user" | "assistant" | "thinking";

type UiChatMessage = {
  id: string;
  sender: ChatSender;
  text: string;
  streaming?: boolean;
  error?: boolean;
};

type ChatHistoryMessagePayload = {
  id?: number;
  message?: string;
  sender?: string;
};

type ChatHistoryPaginationPayload = {
  has_more?: boolean;
  next_before_id?: number | null;
};

type ChatHistoryPayload = {
  error?: string;
  messages?: ChatHistoryMessagePayload[];
  pagination?: ChatHistoryPaginationPayload;
};

type GenerationStatusPayload = {
  error?: string;
  is_generating?: boolean;
  has_replayable_job?: boolean;
};

type StreamParsedEvent = {
  event: string;
  id?: number;
  data: Record<string, unknown>;
};

type PromptAssistController = {
  reset: () => void;
};

type PromptStatusVariant = "info" | "success" | "error";

type PromptStatus = {
  message: string;
  variant: PromptStatusVariant;
};

type TaskEditFormState = {
  old_task: string;
  new_task: string;
  prompt_template: string;
  response_rules: string;
  output_skeleton: string;
  input_examples: string;
  output_examples: string;
};

type StoredHistoryEntry = {
  text: string;
  sender: string;
};

const DEFAULT_MODEL = "openai/gpt-oss-120b";
const CHAT_HISTORY_PAGE_SIZE = 50;
const STICKY_SCROLL_BOTTOM_THRESHOLD_PX = 72;
const THINKING_CONSTELLATION_BASE_WIDTH = 208;
const THINKING_CONSTELLATION_BASE_HEIGHT = 86;
const THINKING_CONSTELLATION_NODES = [
  { x: 22, y: 58, size: 0.92 },
  { x: 37, y: 36, size: 1 },
  { x: 51, y: 49, size: 0.86 },
  { x: 67, y: 34, size: 1.08 },
  { x: 80, y: 46, size: 0.78 },
];
const THINKING_CONSTELLATION_LINKS: Array<[number, number]> = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
];

const roomMenuBaseStyle: CSSProperties = {
  position: "absolute",
  top: "50%",
  right: 0,
  transform: "translateY(-50%)",
  background: "#fff",
  border: "1px solid #ddd",
  borderRadius: "6px",
  boxShadow: "0 2px 4px rgba(0,0,0,.1)",
  zIndex: 10,
  minWidth: "140px",
  overflow: "hidden",
};

const roomMenuItemBaseStyle: CSSProperties = {
  padding: "8px 16px",
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  fontSize: "14px",
  borderBottom: "1px solid #ddd",
};

const FALLBACK_TASKS: NormalizedTask[] = (defaultTasks as TaskItem[]).map((task) => normalizeTask(task));

function normalizeTask(task: TaskItem | null | undefined): NormalizedTask {
  if (!task) {
    return {
      name: "無題",
      prompt_template: "プロンプトテンプレートはありません",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    };
  }

  const name = typeof task.name === "string" && task.name.trim() ? task.name.trim() : "無題";

  return {
    name,
    prompt_template:
      typeof task.prompt_template === "string" && task.prompt_template
        ? task.prompt_template
        : "プロンプトテンプレートはありません",
    response_rules: typeof task.response_rules === "string" ? task.response_rules : "",
    output_skeleton: typeof task.output_skeleton === "string" ? task.output_skeleton : "",
    input_examples: typeof task.input_examples === "string" ? task.input_examples : "",
    output_examples: typeof task.output_examples === "string" ? task.output_examples : "",
    is_default: Boolean(task.is_default),
  };
}

function normalizeTaskList(rawTasks: TaskItem[] | undefined | null): NormalizedTask[] {
  if (!Array.isArray(rawTasks) || rawTasks.length === 0) return FALLBACK_TASKS;
  return rawTasks.map((task) => normalizeTask(task));
}

function parseStreamEventBlock(block: string): StreamParsedEvent | null {
  const lines = block
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0);

  if (lines.length === 0) return null;

  let event = "message";
  let eventId: number | undefined;
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      return;
    }
    if (line.startsWith("id:")) {
      const parsedId = Number.parseInt(line.slice(3).trim(), 10);
      if (Number.isFinite(parsedId) && parsedId > 0) {
        eventId = parsedId;
      }
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  if (dataLines.length === 0) return null;

  try {
    const parsed = parseJsonText(dataLines.join("\n"));
    if (!parsed || typeof parsed !== "object") return null;
    return {
      event,
      id: eventId,
      data: parsed as Record<string, unknown>,
    };
  } catch {
    return null;
  }
}

function isNearBottom(container: HTMLElement, thresholdPx = STICKY_SCROLL_BOTTOM_THRESHOLD_PX) {
  const distanceToBottom = container.scrollHeight - (container.scrollTop + container.clientHeight);
  return distanceToBottom <= thresholdPx;
}

function getStoredHistoryKey(roomId: string) {
  return `chatHistory_${roomId}`;
}

function readStoredHistory(roomId: string): StoredHistoryEntry[] {
  try {
    const raw = localStorage.getItem(getStoredHistoryKey(roomId));
    const parsed = raw ? parseJsonText(raw) : [];
    if (!Array.isArray(parsed)) return [];

    const normalized: StoredHistoryEntry[] = [];
    parsed.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      const text = typeof (entry as { text?: unknown }).text === "string" ? (entry as { text: string }).text : "";
      const sender =
        typeof (entry as { sender?: unknown }).sender === "string"
          ? (entry as { sender: string }).sender
          : "assistant";
      normalized.push({ text, sender });
    });

    return normalized;
  } catch {
    return [];
  }
}

function writeStoredHistory(roomId: string, entries: StoredHistoryEntry[]) {
  try {
    localStorage.setItem(getStoredHistoryKey(roomId), JSON.stringify(entries));
  } catch {
    // ignore localStorage failures
  }
}

function appendStoredHistory(roomId: string, entry: StoredHistoryEntry) {
  const existing = readStoredHistory(roomId);
  writeStoredHistory(roomId, [...existing, entry]);
}

function prependStoredHistory(roomId: string, entries: StoredHistoryEntry[]) {
  const existing = readStoredHistory(roomId);
  writeStoredHistory(roomId, [...entries, ...existing]);
}

function normalizeHistorySender(sender: string | undefined): ChatSender {
  if (sender === "user") return "user";
  if (sender === "thinking") return "thinking";
  return "assistant";
}

function toStoredSender(sender: ChatSender): string {
  if (sender === "user") return "user";
  return "bot";
}

function normalizeStoredSender(sender: string): ChatSender {
  return sender === "user" ? "user" : "assistant";
}

function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(STORAGE_KEYS.authStateCache);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // ignore localStorage failures
  }
  return null;
}

function isCachedAuthStateFresh() {
  try {
    const cachedAtRaw = localStorage.getItem(STORAGE_KEYS.authStateCachedAt);
    if (!cachedAtRaw) return false;
    const cachedAt = Number(cachedAtRaw);
    if (!Number.isFinite(cachedAt)) return false;
    return Date.now() - cachedAt <= CACHE_TTL_MS.authState;
  } catch {
    return false;
  }
}

function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(STORAGE_KEYS.authStateCache, loggedIn ? "1" : "0");
    localStorage.setItem(STORAGE_KEYS.authStateCachedAt, String(Date.now()));
  } catch {
    // ignore localStorage failures
  }
}

function consumeAuthSuccessHint() {
  if (typeof window === "undefined") return false;

  const url = new URL(window.location.href);
  if (url.searchParams.get(AUTH_SUCCESS_HINT.queryParam) !== AUTH_SUCCESS_HINT.successValue) {
    return false;
  }

  writeCachedAuthState(true);
  url.searchParams.delete(AUTH_SUCCESS_HINT.queryParam);
  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, document.title, nextUrl || "/");
  return true;
}

function nextMessageId(prefix: string, seqRef: MutableRefObject<number>) {
  seqRef.current += 1;
  return `${prefix}-${Date.now()}-${seqRef.current}`;
}

function ThinkingConstellation() {
  const baseNodeSize = Math.max(4, THINKING_CONSTELLATION_BASE_WIDTH * 0.03);

  const links = THINKING_CONSTELLATION_LINKS.map(([fromIndex, toIndex], index) => {
    const fromNode = THINKING_CONSTELLATION_NODES[fromIndex];
    const toNode = THINKING_CONSTELLATION_NODES[toIndex];
    if (!fromNode || !toNode) {
      return null;
    }

    const dx = ((toNode.x - fromNode.x) / 100) * THINKING_CONSTELLATION_BASE_WIDTH;
    const dy = ((toNode.y - fromNode.y) / 100) * THINKING_CONSTELLATION_BASE_HEIGHT;
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const length = Math.hypot(dx, dy);

    return (
      <span
        key={`thinking-link-${index}`}
        className="constellation-loader__link"
        style={{
          left: `${fromNode.x}%`,
          top: `${fromNode.y}%`,
          width: `${length}px`,
          opacity: 1,
          transform: `translateY(-50%) rotate(${angle}deg)`,
          ["--link-delay" as string]: `${index * -0.16}s`,
        }}
      ></span>
    );
  });

  const nodes = Array.from({ length: 8 }).map((_, index) => {
    const node = THINKING_CONSTELLATION_NODES[index];
    if (!node) {
      return <span key={`thinking-node-${index}`} className="constellation-loader__node"></span>;
    }

    return (
      <span
        key={`thinking-node-${index}`}
        className="constellation-loader__node"
        style={{
          left: `${node.x}%`,
          top: `${node.y}%`,
          width: `${baseNodeSize * node.size}px`,
          height: `${baseNodeSize * node.size}px`,
          opacity: 1,
          transform: "translate(-50%, -50%) scale(1)",
          ["--node-delay" as string]: `${index * -0.18}s`,
        }}
      ></span>
    );
  });

  return (
    <div className="constellation-loader thinking-message__constellation is-ready" aria-hidden="true">
      {links}
      {nodes}
    </div>
  );
}

function BotMessageHtml({ text }: { text: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => formatLLMOutput(text), [text]);

  useEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}

function CopyActionButton({ getText }: { getText: () => string }) {
  const [iconClass, setIconClass] = useState("bi-clipboard");
  const [statusClass, setStatusClass] = useState("");

  const handleClick = useCallback(async () => {
    try {
      await copyTextToClipboard(getText());
      setIconClass("bi-check-lg");
      setStatusClass("copy-btn--success");
    } catch {
      setIconClass("bi-x-lg");
      setStatusClass("copy-btn--error");
    } finally {
      window.setTimeout(() => {
        setIconClass("bi-clipboard");
        setStatusClass("");
      }, 2000);
    }
  }, [getText]);

  return (
    <button
      type="button"
      className={`copy-btn message-action-btn ${statusClass}`.trim()}
      aria-label="メッセージをコピー"
      data-tooltip="このメッセージをコピー"
      data-tooltip-placement="top"
      onClick={() => {
        void handleClick();
      }}
    >
      <i className={`bi ${iconClass}`}></i>
    </button>
  );
}

function MemoSaveActionButton({ getText }: { getText: () => string }) {
  const [iconClass, setIconClass] = useState("bi-bookmark-plus");
  const [variantClass, setVariantClass] = useState("");
  const [disabled, setDisabled] = useState(false);

  const handleClick = useCallback(async () => {
    if (disabled) return;

    const aiResponse = getText().trim();
    if (!aiResponse) {
      setIconClass("bi-x-lg");
      setVariantClass("memo-save-btn--error");
      window.setTimeout(() => {
        setIconClass("bi-bookmark-plus");
        setVariantClass("");
      }, 2000);
      return;
    }

    setDisabled(true);
    setVariantClass("memo-save-btn--loading");
    setIconClass("bi-hourglass-split");

    try {
      const response = await fetch("/memo/api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          input_content: "",
          ai_response: aiResponse,
          title: "",
          tags: "",
        }),
      });

      const rawPayload = await readJsonBodySafe(response);
      const status =
        rawPayload && typeof rawPayload === "object" && "status" in rawPayload
          ? (rawPayload as { status?: unknown }).status
          : undefined;

      if (!response.ok || status === "fail") {
        throw new Error(extractApiErrorMessage(rawPayload, "メモの保存に失敗しました。", response.status));
      }

      setIconClass("bi-check-lg");
      setVariantClass("memo-save-btn--success");
    } catch {
      setIconClass("bi-x-lg");
      setVariantClass("memo-save-btn--error");
    } finally {
      setDisabled(false);
      window.setTimeout(() => {
        setIconClass("bi-bookmark-plus");
        setVariantClass("");
      }, 2000);
    }
  }, [disabled, getText]);

  return (
    <button
      type="button"
      className={`memo-save-btn message-action-btn ${variantClass}`.trim()}
      aria-label="メモに保存"
      data-tooltip="この回答をメモに保存"
      data-tooltip-placement="top"
      disabled={disabled}
      onClick={() => {
        void handleClick();
      }}
    >
      <i className={`bi ${iconClass}`}></i>
    </button>
  );
}

export default function HomePage() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  const [isChatVisible, setIsChatVisible] = useState(false);
  const [setupInfo, setSetupInfo] = useState("");

  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);

  const [tasks, setTasks] = useState<NormalizedTask[]>(FALLBACK_TASKS);
  const [tasksExpanded, setTasksExpanded] = useState(false);
  const [isTaskOrderEditing, setIsTaskOrderEditing] = useState(false);
  const [taskDetail, setTaskDetail] = useState<NormalizedTask | null>(null);

  const [isNewPromptModalOpen, setIsNewPromptModalOpen] = useState(false);
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [newPromptTitle, setNewPromptTitle] = useState("");
  const [newPromptContent, setNewPromptContent] = useState("");
  const [newPromptInputExample, setNewPromptInputExample] = useState("");
  const [newPromptOutputExample, setNewPromptOutputExample] = useState("");
  const [newPromptStatus, setNewPromptStatus] = useState<PromptStatus>({ message: "", variant: "info" });
  const [isPromptSubmitting, setIsPromptSubmitting] = useState(false);

  const [taskEditModalOpen, setTaskEditModalOpen] = useState(false);
  const [taskEditForm, setTaskEditForm] = useState<TaskEditFormState>({
    old_task: "",
    new_task: "",
    prompt_template: "",
    response_rules: "",
    output_skeleton: "",
    input_examples: "",
    output_examples: "",
  });

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

  const [draggingTaskIndex, setDraggingTaskIndex] = useState<number | null>(null);
  const taskLaunchInProgressRef = useRef(false);

  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState<{ message: string; error: boolean }>({
    message: "共有するチャットルームを選択してください。",
    error: false,
  });
  const [shareUrl, setShareUrl] = useState("");
  const [shareLoading, setShareLoading] = useState(false);

  const modelSelectRef = useRef<HTMLDivElement | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const newPromptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const contentInputRef = useRef<HTMLTextAreaElement | null>(null);
  const inputExampleRef = useRef<HTMLTextAreaElement | null>(null);
  const outputExampleRef = useRef<HTMLTextAreaElement | null>(null);

  const promptAssistControllerRef = useRef<PromptAssistController | null>(null);
  const shareCacheRef = useRef<Map<string, string>>(new Map());
  const currentRoomIdRef = useRef<string | null>(null);
  const streamLastEventIdByRoomRef = useRef<Map<string, number>>(new Map());
  const abortControllerRef = useRef<AbortController | null>(null);
  const messageSeqRef = useRef(0);
  const pendingAutoScrollRef = useRef(false);
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);

  const hasCurrentRoom = Boolean(currentRoomId);
  const showTaskToggleButton = tasks.length > 6 && !isTaskOrderEditing;
  const visibleTaskCountText = tasksExpanded || isTaskOrderEditing ? "閉じる" : "もっと見る";

  const selectedModelLabel = useMemo(() => {
    const options: Array<{ value: string; label: string }> = [
      { value: "openai/gpt-oss-120b", label: "GROQ | GPT-OSS 120B（標準・高品質な応答）" },
      { value: "gpt-5-mini-2025-08-07", label: "OPENAI | GPT-5 MINI（高品質・推論が必要な作業向け）" },
      { value: "gemini-2.5-flash", label: "GEMINI | 2.5 FLASH（軽い作業向け）" },
    ];
    return options.find((option) => option.value === selectedModel)?.label ?? options[0].label;
  }, [selectedModel]);

  const scheduleAutoScrollIfNeeded = useCallback((force = false) => {
    const container = chatMessagesRef.current;
    if (!container) {
      pendingAutoScrollRef.current = true;
      return;
    }
    if (force || isNearBottom(container)) {
      pendingAutoScrollRef.current = true;
    }
  }, []);

  const persistCurrentRoomId = useCallback((roomId: string | null) => {
    currentRoomIdRef.current = roomId;
    setCurrentRoomId(roomId);
    try {
      if (roomId) {
        localStorage.setItem(STORAGE_KEYS.currentChatRoomId, roomId);
      } else {
        localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
      }
    } catch {
      // ignore localStorage failures
    }
  }, []);

  const removeThinkingMessages = useCallback((list: UiChatMessage[]) => {
    return list.filter((message) => message.sender !== "thinking");
  }, []);

  const appendAssistantErrorMessage = useCallback(
    (roomId: string, errorMessage: string) => {
      const id = nextMessageId("assistant-error", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id,
            sender: "assistant",
            text: `エラー: ${errorMessage}`,
            error: true,
          },
        ];
      });
      scheduleAutoScrollIfNeeded(true);
    },
    [removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const saveUiMessagesToLocalStorage = useCallback((roomId: string, uiMessages: UiChatMessage[]) => {
    const normalized = uiMessages
      .filter((message) => message.sender === "user" || message.sender === "assistant")
      .map((message) => ({
        text: message.text,
        sender: toStoredSender(message.sender),
      }));
    writeStoredHistory(roomId, normalized);
  }, []);

  const loadLocalChatHistory = useCallback(
    (roomId: string) => {
      const localEntries = readStoredHistory(roomId);
      const localMessages: UiChatMessage[] = localEntries.map((entry) => ({
        id: nextMessageId("local", messageSeqRef),
        sender: normalizeStoredSender(entry.sender),
        text: entry.text,
      }));

      setMessages(localMessages);
      setHistoryHasMore(false);
      setHistoryNextBeforeId(null);
      scheduleAutoScrollIfNeeded(true);
    },
    [scheduleAutoScrollIfNeeded],
  );

  const fetchChatHistoryPage = useCallback(async (roomId: string, beforeId?: number | null) => {
    const params = new URLSearchParams({
      room_id: roomId,
      limit: String(CHAT_HISTORY_PAGE_SIZE),
    });
    if (typeof beforeId === "number") {
      params.set("before_id", String(beforeId));
    }

    const response = await fetch(`/api/get_chat_history?${params.toString()}`, {
      credentials: "same-origin",
    });
    const rawPayload = (await readJsonBodySafe(response)) as ChatHistoryPayload;

    if (!response.ok || rawPayload.error) {
      throw new Error(extractApiErrorMessage(rawPayload, "履歴取得に失敗しました。", response.status));
    }

    const historyMessages = Array.isArray(rawPayload.messages) ? rawPayload.messages : [];
    const pagination = rawPayload.pagination || {};

    return {
      messages: historyMessages,
      pagination: {
        has_more: pagination.has_more === true,
        next_before_id: typeof pagination.next_before_id === "number" ? pagination.next_before_id : null,
      },
    };
  }, []);

  const consumeStreamingChatResponse = useCallback(
    async (response: Response, roomId: string) => {
      if (!response.body) {
        throw new Error("ストリーム応答を受信できませんでした。");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      let streamError: string | null = null;
      let streamingMessageId: string | null = null;
      let streamedText = "";

      const ensureStreamingMessage = () => {
        if (streamingMessageId) return streamingMessageId;
        streamingMessageId = nextMessageId("assistant-stream", messageSeqRef);
        const newId = streamingMessageId;

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          return [
            ...removeThinkingMessages(previous),
            {
              id: newId,
              sender: "assistant",
              text: "",
              streaming: true,
            },
          ];
        });
        scheduleAutoScrollIfNeeded();
        return newId;
      };

      const finalizeStreamingMessage = (finalText: string, persist = true) => {
        if (!streamingMessageId) {
          if (finalText) {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId) return previous;
              return [
                ...removeThinkingMessages(previous),
                {
                  id: nextMessageId("assistant", messageSeqRef),
                  sender: "assistant",
                  text: finalText,
                },
              ];
            });
          } else {
            setMessages((previous) => {
              if (currentRoomIdRef.current !== roomId) return previous;
              return removeThinkingMessages(previous);
            });
          }
          if (persist && finalText) {
            appendStoredHistory(roomId, { text: finalText, sender: "bot" });
          }
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        const streamId = streamingMessageId;
        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          return removeThinkingMessages(previous).map((message) => {
            if (message.id !== streamId) return message;
            return {
              ...message,
              text: finalText || message.text,
              streaming: false,
            };
          });
        });

        if (persist && finalText) {
          appendStoredHistory(roomId, { text: finalText, sender: "bot" });
        }
        scheduleAutoScrollIfNeeded(true);
      };

      const processBlock = (block: string) => {
        const parsed = parseStreamEventBlock(block);
        if (!parsed) return;

        if (typeof parsed.id === "number" && parsed.id > 0) {
          streamLastEventIdByRoomRef.current.set(roomId, parsed.id);
        }

        if (parsed.event === "chunk") {
          const text = typeof parsed.data.text === "string" ? parsed.data.text : "";
          if (!text) return;
          const streamId = ensureStreamingMessage();
          streamedText += text;

          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return previous.map((message) => {
              if (message.id !== streamId) return message;
              return {
                ...message,
                text: streamedText,
                streaming: true,
              };
            });
          });
          scheduleAutoScrollIfNeeded();
          return;
        }

        if (parsed.event === "done") {
          completed = true;
          const responseText = typeof parsed.data.response === "string" ? parsed.data.response : streamedText;
          finalizeStreamingMessage(responseText, true);
          streamLastEventIdByRoomRef.current.delete(roomId);
          return;
        }

        if (parsed.event === "aborted") {
          completed = true;
          finalizeStreamingMessage(streamedText, false);
          return;
        }

        if (parsed.event === "error") {
          streamError =
            typeof parsed.data.message === "string"
              ? parsed.data.message
              : "ストリーミング生成中にエラーが発生しました。";
        }
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() || "";
          blocks.forEach(processBlock);

          if (streamError) break;
          if (done) break;
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          finalizeStreamingMessage(streamedText, false);
          return;
        }
        throw error;
      } finally {
        reader.cancel().catch(() => {
          // no-op
        });
      }

      if (streamError) {
        if (streamedText) {
          finalizeStreamingMessage(streamedText, false);
        } else {
          appendAssistantErrorMessage(roomId, streamError);
        }
        return;
      }

      if (!completed) {
        appendAssistantErrorMessage(roomId, "ストリームが途中で終了しました。");
      }
    },
    [appendAssistantErrorMessage, removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const connectToGenerationStream = useCallback(
    async (roomId: string) => {
      if (isGenerating) return;

      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      setIsGenerating(true);

      const thinkingId = nextMessageId("thinking", messageSeqRef);
      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [
          ...removeThinkingMessages(previous),
          {
            id: thinkingId,
            sender: "thinking",
            text: "",
          },
        ];
      });

      const headers: Record<string, string> = {};
      const lastEventId = streamLastEventIdByRoomRef.current.get(roomId);
      if (typeof lastEventId === "number" && lastEventId > 0) {
        headers["Last-Event-ID"] = String(lastEventId);
      }

      try {
        const response = await fetch(`/api/chat_generation_stream?room_id=${encodeURIComponent(roomId)}`, {
          credentials: "same-origin",
          signal: abortController.signal,
          headers,
        });

        if (!response.ok) {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
          return;
        }

        await consumeStreamingChatResponse(response, roomId);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
        }
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
          setIsGenerating(false);
        }
      }
    },
    [consumeStreamingChatResponse, isGenerating, removeThinkingMessages],
  );

  const loadChatHistory = useCallback(
    async (roomId: string, shouldCheckGeneration = true) => {
      try {
        const { messages: historyMessages, pagination } = await fetchChatHistoryPage(roomId);
        if (currentRoomIdRef.current !== roomId) return;

        const uiMessages: UiChatMessage[] = historyMessages.map((entry) => ({
          id: nextMessageId("history", messageSeqRef),
          sender: normalizeHistorySender(entry.sender),
          text: typeof entry.message === "string" ? entry.message : "",
        }));

        setHistoryHasMore(pagination.has_more === true);
        setHistoryNextBeforeId(typeof pagination.next_before_id === "number" ? pagination.next_before_id : null);

        if (!shouldCheckGeneration) {
          setMessages(uiMessages);
          saveUiMessagesToLocalStorage(roomId, uiMessages);
          scheduleAutoScrollIfNeeded(true);
          return;
        }

        let generationStatus: GenerationStatusPayload = {};
        try {
          const statusResponse = await fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`, {
            credentials: "same-origin",
          });
          generationStatus = (await readJsonBodySafe(statusResponse)) as GenerationStatusPayload;
        } catch {
          generationStatus = {};
        }

        if (currentRoomIdRef.current !== roomId) return;

        if (generationStatus.is_generating) {
          setMessages(uiMessages);
          saveUiMessagesToLocalStorage(roomId, uiMessages);
          scheduleAutoScrollIfNeeded(true);
          void connectToGenerationStream(roomId);
          return;
        }

        if (generationStatus.has_replayable_job) {
          let lastAssistantIndex = -1;
          for (let i = uiMessages.length - 1; i >= 0; i -= 1) {
            if (uiMessages[i]?.sender === "assistant") {
              lastAssistantIndex = i;
              break;
            }
          }

          const replayBaseMessages =
            lastAssistantIndex >= 0
              ? [...uiMessages.slice(0, lastAssistantIndex), ...uiMessages.slice(lastAssistantIndex + 1)]
              : uiMessages;

          setMessages(replayBaseMessages);
          saveUiMessagesToLocalStorage(roomId, replayBaseMessages);
          scheduleAutoScrollIfNeeded(true);
          void connectToGenerationStream(roomId);
          return;
        }

        setMessages(uiMessages);
        saveUiMessagesToLocalStorage(roomId, uiMessages);
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        console.error("履歴取得失敗:", error);
      }
    },
    [connectToGenerationStream, fetchChatHistoryPage, saveUiMessagesToLocalStorage, scheduleAutoScrollIfNeeded],
  );

  const loadOlderChatHistory = useCallback(async () => {
    const roomId = currentRoomIdRef.current;
    if (!roomId) return;
    if (!historyHasMore) return;
    if (historyNextBeforeId === null) return;
    if (isLoadingOlder) return;

    const container = chatMessagesRef.current;
    if (!container) return;

    setIsLoadingOlder(true);
    prependScrollRestoreRef.current = {
      prevScrollHeight: container.scrollHeight,
      prevScrollTop: container.scrollTop,
    };

    try {
      const { messages: olderMessages, pagination } = await fetchChatHistoryPage(roomId, historyNextBeforeId);
      if (currentRoomIdRef.current !== roomId) return;

      const uiMessages = olderMessages.map((entry) => ({
        id: nextMessageId("history-older", messageSeqRef),
        sender: normalizeHistorySender(entry.sender),
        text: typeof entry.message === "string" ? entry.message : "",
      }));

      setMessages((previous) => [...uiMessages, ...previous]);
      setHistoryHasMore(pagination.has_more === true);
      setHistoryNextBeforeId(typeof pagination.next_before_id === "number" ? pagination.next_before_id : null);

      prependStoredHistory(
        roomId,
        uiMessages
          .filter((message) => message.sender === "user" || message.sender === "assistant")
          .map((message) => ({ text: message.text, sender: toStoredSender(message.sender) })),
      );
    } catch (error) {
      console.error("追加履歴取得失敗:", error);
      prependScrollRestoreRef.current = null;
    } finally {
      setIsLoadingOlder(false);
    }
  }, [fetchChatHistoryPage, historyHasMore, historyNextBeforeId, isLoadingOlder]);

  const loadChatRooms = useCallback(async () => {
    try {
      const response = await fetch("/api/get_chat_rooms", { credentials: "same-origin" });
      const rawPayload = await readJsonBodySafe(response);
      const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { rooms?: unknown[]; error?: unknown }) : {};

      if (typeof data.error === "string" && data.error) {
        console.error("get_chat_rooms:", data.error);
        return;
      }

      const rooms = Array.isArray(data.rooms) ? data.rooms : [];
      const normalizedRooms: ChatRoom[] = rooms
        .map((room): ChatRoom | null => {
          if (!room || typeof room !== "object") return null;
          const payload = room as { id?: unknown; title?: unknown; created_at?: unknown };
          if (payload.id === undefined || payload.id === null) return null;
          return {
            id: String(payload.id),
            title: typeof payload.title === "string" && payload.title.trim() ? payload.title : "新規チャット",
            created_at: typeof payload.created_at === "string" ? payload.created_at : undefined,
          };
        })
        .filter((room): room is ChatRoom => room !== null);

      setChatRooms(normalizedRooms);
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
    }
  }, []);

  const switchChatRoom = useCallback(
    (roomId: string) => {
      persistCurrentRoomId(roomId);
      setIsChatVisible(true);
      setSidebarOpen(false);
      setOpenRoomActionsFor(null);
      setShareStatus({ message: "共有リンクを準備しています...", error: false });
      setShareUrl("");
      loadLocalChatHistory(roomId);
      void loadChatHistory(roomId, true);
      void loadChatRooms();
    },
    [loadChatHistory, loadChatRooms, loadLocalChatHistory, persistCurrentRoomId],
  );

  const createNewChatRoom = useCallback(async (roomId: string, title: string) => {
    const response = await fetch("/api/new_chat_room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ id: roomId, title }),
    });

    const payload = (await readJsonBodySafe(response)) as { error?: string };
    if (!response.ok || payload.error) {
      throw new Error(extractApiErrorMessage(payload, "チャットルーム作成に失敗しました。", response.status));
    }
  }, []);

  const generateResponse = useCallback(
    async (message: string, model: string, roomId: string) => {
      if (isGenerating) return;

      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      setIsGenerating(true);

      const userMessage: UiChatMessage = {
        id: nextMessageId("user", messageSeqRef),
        sender: "user",
        text: message,
      };
      const thinkingMessage: UiChatMessage = {
        id: nextMessageId("thinking", messageSeqRef),
        sender: "thinking",
        text: "",
      };

      setMessages((previous) => {
        if (currentRoomIdRef.current !== roomId) return previous;
        return [...removeThinkingMessages(previous), userMessage, thinkingMessage];
      });
      appendStoredHistory(roomId, { text: message, sender: "user" });
      streamLastEventIdByRoomRef.current.set(roomId, 0);
      scheduleAutoScrollIfNeeded(true);

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            message,
            chat_room_id: roomId,
            model,
          }),
          signal: abortController.signal,
        });

        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
          await consumeStreamingChatResponse(response, roomId);
          return;
        }

        const rawPayload = await readJsonBodySafe(response);
        const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { response?: unknown; error?: unknown }) : {};

        setMessages((previous) => {
          if (currentRoomIdRef.current !== roomId) return previous;
          const trimmed = removeThinkingMessages(previous);

          if (response.ok && typeof data.response === "string" && data.response) {
            return [
              ...trimmed,
              {
                id: nextMessageId("assistant", messageSeqRef),
                sender: "assistant",
                text: data.response,
              },
            ];
          }

          return [
            ...trimmed,
            {
              id: nextMessageId("assistant-error", messageSeqRef),
              sender: "assistant",
              text: `エラー: ${extractApiErrorMessage(rawPayload, "予期しないエラーが発生しました。", response.status)}`,
              error: true,
            },
          ];
        });

        if (response.ok && typeof data.response === "string" && data.response) {
          appendStoredHistory(roomId, { text: data.response, sender: "bot" });
        }
        scheduleAutoScrollIfNeeded(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          setMessages((previous) => {
            if (currentRoomIdRef.current !== roomId) return previous;
            return removeThinkingMessages(previous);
          });
          return;
        }

        const errorMessage = error instanceof Error ? error.message : String(error);
        appendAssistantErrorMessage(roomId, errorMessage);
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
          setIsGenerating(false);
        }
      }
    },
    [appendAssistantErrorMessage, consumeStreamingChatResponse, isGenerating, removeThinkingMessages, scheduleAutoScrollIfNeeded],
  );

  const stopGeneration = useCallback(async () => {
    const abortController = abortControllerRef.current;
    if (abortController) {
      abortController.abort();
      abortControllerRef.current = null;
      setIsGenerating(false);
    }

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    try {
      await fetch("/api/chat_stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ chat_room_id: roomId }),
      });
    } catch {
      // best effort
    }
  }, []);

  const refreshTasks = useCallback(
    async (forceRefresh = false) => {
      if (!forceRefresh) {
        const cached = readCachedTasks();
        if (Array.isArray(cached) && cached.length > 0) {
          setTasks(normalizeTaskList(cached));
          return;
        }
      }

      setTasks(FALLBACK_TASKS);

      try {
        const { payload } = await fetchJsonOrThrow<{ tasks?: TaskItem[] }>("/api/tasks", undefined, {
          defaultMessage: "タスクの読み込みに失敗しました。",
        });

        const fetchedTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
        if (fetchedTasks.length > 0) {
          writeCachedTasks(fetchedTasks);
        }

        setTasks(normalizeTaskList(fetchedTasks));
      } catch (error) {
        console.error("タスク読み込みに失敗:", error);
        setTasks(FALLBACK_TASKS);
      }
    },
    [],
  );

  const saveTaskOrder = useCallback(async (nextTasks: NormalizedTask[]) => {
    const order = nextTasks
      .filter((task) => !task.is_default)
      .map((task) => task.name)
      .filter((name) => Boolean(name));

    if (order.length === 0) return;

    try {
      await fetchJsonOrThrow("/api/update_tasks_order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ order }),
      });
      invalidateTasksCache();
    } catch (error) {
      const message = error instanceof Error ? error.message : "並び順の保存に失敗しました。";
      window.alert(`並び順の保存に失敗: ${message}`);
    }
  }, []);

  const closeShareModal = useCallback(() => {
    setShareModalOpen(false);
  }, []);

  const resetNewPromptComposer = useCallback(() => {
    setIsPromptSubmitting(false);
    setNewPromptStatus({ message: "", variant: "info" });
    promptAssistControllerRef.current?.reset();
  }, []);

  const closeNewPromptModal = useCallback(() => {
    setIsNewPromptModalOpen(false);
    resetNewPromptComposer();
  }, [resetNewPromptComposer]);

  const openNewPromptModal = useCallback(() => {
    setIsNewPromptModalOpen(true);
    setNewPromptStatus({
      message: "タイトルか本文がある状態で AI 補助を使うと、提案の精度が上がります。",
      variant: "info",
    });
  }, []);

  const setShareActionLoading = useCallback((loading: boolean) => {
    setShareLoading(loading);
  }, []);

  const createShareLink = useCallback(
    async (forceRefresh = false) => {
      const roomId = currentRoomIdRef.current;
      if (!roomId) {
        setShareStatus({ message: "共有するチャットルームを選択してください。", error: true });
        setShareUrl("");
        return;
      }

      if (!forceRefresh && shareCacheRef.current.has(roomId)) {
        const cached = shareCacheRef.current.get(roomId) || "";
        setShareUrl(cached);
        setShareStatus({ message: "共有リンクを表示しています。", error: false });
        return;
      }

      setShareActionLoading(true);
      setShareStatus({ message: "共有リンクを生成しています...", error: false });

      try {
        const response = await fetch("/api/share_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const rawPayload = await readJsonBodySafe(response);
        const data = rawPayload && typeof rawPayload === "object" ? (rawPayload as { share_url?: unknown }) : {};

        if (!response.ok || typeof data.share_url !== "string" || !data.share_url) {
          throw new Error(extractApiErrorMessage(rawPayload, "共有リンクの作成に失敗しました。", response.status));
        }

        shareCacheRef.current.set(roomId, data.share_url);
        setShareUrl(data.share_url);
        setShareStatus({ message: "共有リンクを作成しました。", error: false });
      } catch (error) {
        setShareStatus({
          message: error instanceof Error ? error.message : "共有リンクの作成に失敗しました。",
          error: true,
        });
      } finally {
        setShareActionLoading(false);
      }
    },
    [setShareActionLoading],
  );

  const openShareModal = useCallback(() => {
    setShareModalOpen(true);
    void createShareLink(false);
  }, [createShareLink]);

  const copyShareLink = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }

    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ message: "リンクをコピーしました。", error: false });
    } catch (error) {
      setShareStatus({
        message: error instanceof Error ? error.message : "リンクのコピーに失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  const shareWithNativeSheet = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }
    if (!navigator.share) {
      setShareStatus({ message: "このブラウザはネイティブ共有に対応していません。", error: true });
      return;
    }

    try {
      await navigator.share({
        title: "Chat Core 共有チャット",
        text: "このチャットルームを共有しました。",
        url: shareUrl,
      });
      setShareStatus({ message: "共有シートを開きました。", error: false });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setShareStatus({
        message: error instanceof Error ? error.message : "共有に失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  const showSetupForm = useCallback(() => {
    setIsChatVisible(false);
    setSidebarOpen(false);
    setSetupInfo("");
    closeShareModal();
    scheduleSetupViewportFit();
  }, [closeShareModal]);

  const handleAccessChat = useCallback(async () => {
    try {
      const response = await fetch("/api/get_chat_rooms", { credentials: "same-origin" });
      const payload = (await readJsonBodySafe(response)) as { rooms?: Array<{ id?: unknown; title?: unknown }> };
      const rooms = Array.isArray(payload.rooms)
        ? payload.rooms
            .map((room) => {
              if (!room || typeof room !== "object") return null;
              const item = room as { id?: unknown; title?: unknown };
              if (item.id === undefined || item.id === null) return null;
              return {
                id: String(item.id),
                title: typeof item.title === "string" ? item.title : "新規チャット",
              } as ChatRoom;
            })
            .filter((room): room is ChatRoom => room !== null)
        : [];

      if (rooms.length > 0) {
        setChatRooms(rooms);
        switchChatRoom(rooms[0].id);
        return;
      }

      setIsChatVisible(true);
      setMessages([]);
      persistCurrentRoomId(null);
      void loadChatRooms();
    } catch (error) {
      console.error("ルーム一覧取得失敗:", error);
      setIsChatVisible(true);
      setMessages([]);
      persistCurrentRoomId(null);
      void loadChatRooms();
    }
  }, [loadChatRooms, persistCurrentRoomId, switchChatRoom]);

  const handleNewChat = useCallback(() => {
    persistCurrentRoomId(null);
    setMessages([]);
    setShareUrl("");
    setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
    showSetupForm();
  }, [persistCurrentRoomId, showSetupForm]);

  const handleTaskCardLaunch = useCallback(
    async (task: NormalizedTask) => {
      if (isTaskOrderEditing) return;
      if (taskLaunchInProgressRef.current) return;

      taskLaunchInProgressRef.current = true;

      const roomId = Date.now().toString();
      const currentSetupInfo = setupInfo.trim();
      const roomTitle = currentSetupInfo || "新規チャット";
      const firstMessage = currentSetupInfo
        ? `【タスク】${task.name}\n【状況・作業環境】${currentSetupInfo}`
        : `【タスク】${task.name}`;

      persistCurrentRoomId(roomId);

      try {
        await createNewChatRoom(roomId, roomTitle);
        setIsChatVisible(true);
        setMessages([]);
        setChatInput("");
        setOpenRoomActionsFor(null);
        setShareUrl("");
        setShareStatus({ message: "共有リンクを準備しています...", error: false });

        try {
          localStorage.removeItem(getStoredHistoryKey(roomId));
        } catch {
          // ignore localStorage failures
        }

        void loadChatRooms();
        await generateResponse(firstMessage, selectedModel, roomId);
      } catch (error) {
        window.alert(`チャットルーム作成に失敗: ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        taskLaunchInProgressRef.current = false;
      }
    },
    [createNewChatRoom, generateResponse, isTaskOrderEditing, loadChatRooms, persistCurrentRoomId, selectedModel, setupInfo],
  );

  const handleSendMessage = useCallback(() => {
    if (isGenerating) {
      void stopGeneration();
      return;
    }

    const roomId = currentRoomIdRef.current;
    if (!roomId) return;

    const message = chatInput.trim();
    if (!message) return;

    setChatInput("");
    void generateResponse(message, selectedModel, roomId);
  }, [chatInput, generateResponse, isGenerating, selectedModel, stopGeneration]);

  const handleChatInputKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLInputElement>) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      handleSendMessage();
    },
    [handleSendMessage],
  );

  const handleDeleteRoom = useCallback(
    async (roomId: string, roomTitle: string) => {
      const confirmed = await showConfirmModal(`「${roomTitle}」を削除しますか？`);
      if (!confirmed) return;

      try {
        const response = await fetch("/api/delete_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, "削除失敗", response.status));
        }

        if (roomId === currentRoomIdRef.current) {
          persistCurrentRoomId(null);
          setMessages([]);
          setShareUrl("");
          setShareStatus({ message: "共有するチャットルームを選択してください。", error: false });
          closeShareModal();
        }

        setOpenRoomActionsFor(null);
        void loadChatRooms();
      } catch (error) {
        window.alert(`削除失敗: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [closeShareModal, loadChatRooms, persistCurrentRoomId],
  );

  const handleRenameRoom = useCallback(
    async (roomId: string, currentTitle: string) => {
      const nextTitle = window.prompt("新しいチャットルーム名", currentTitle);
      if (!nextTitle || !nextTitle.trim()) return;

      try {
        const response = await fetch("/api/rename_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId, new_title: nextTitle.trim() }),
        });
        const payload = await readJsonBodySafe(response);

        if (!response.ok) {
          throw new Error(extractApiErrorMessage(payload, "名前変更失敗", response.status));
        }

        setOpenRoomActionsFor(null);
        void loadChatRooms();
      } catch (error) {
        window.alert(`名前変更失敗: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [loadChatRooms],
  );

  const toggleTaskOrderEditing = useCallback(() => {
    setIsTaskOrderEditing((previous) => {
      const next = !previous;
      if (next) {
        setTasksExpanded(true);
      } else {
        void saveTaskOrder(tasks);
      }
      return next;
    });
  }, [saveTaskOrder, tasks]);

  const handleTaskDragStart = useCallback(
    (event: React.DragEvent<HTMLDivElement>, index: number) => {
      if (!isTaskOrderEditing) return;
      setDraggingTaskIndex(index);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>, hoverIndex: number) => {
      if (!isTaskOrderEditing) return;
      event.preventDefault();

      const dragIndexRaw = event.dataTransfer.getData("text/plain");
      const dragIndex = Number.parseInt(dragIndexRaw, 10);
      if (!Number.isFinite(dragIndex)) return;
      if (dragIndex === hoverIndex) return;

      setTasks((previous) => {
        if (dragIndex < 0 || dragIndex >= previous.length) return previous;
        if (hoverIndex < 0 || hoverIndex >= previous.length) return previous;

        const next = [...previous];
        const [moved] = next.splice(dragIndex, 1);
        if (!moved) return previous;
        next.splice(hoverIndex, 0, moved);

        event.dataTransfer.setData("text/plain", String(hoverIndex));
        setDraggingTaskIndex(hoverIndex);

        return next;
      });
    },
    [isTaskOrderEditing],
  );

  const handleTaskDragEnd = useCallback(() => {
    setDraggingTaskIndex(null);
  }, []);

  const handleTaskDelete = useCallback(
    async (taskName: string) => {
      const confirmed = await showConfirmModal("このタスクを削除してもよろしいですか？");
      if (!confirmed) return;

      try {
        await fetchJsonOrThrow("/api/delete_task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ task: taskName }),
        });

        setTasks((previous) => {
          const next = previous.filter((task) => task.name !== taskName);
          void saveTaskOrder(next);
          return next;
        });
        invalidateTasksCache();
      } catch (error) {
        window.alert(`削除に失敗しました: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [saveTaskOrder],
  );

  const openTaskEditModal = useCallback((task: NormalizedTask) => {
    setTaskEditForm({
      old_task: task.name,
      new_task: task.name,
      prompt_template: task.prompt_template,
      response_rules: task.response_rules,
      output_skeleton: task.output_skeleton,
      input_examples: task.input_examples,
      output_examples: task.output_examples,
    });
    setTaskEditModalOpen(true);
  }, []);

  const closeTaskEditModal = useCallback(() => {
    setTaskEditModalOpen(false);
  }, []);

  const handleTaskEditSave = useCallback(async () => {
    const payload = {
      old_task: taskEditForm.old_task,
      new_task: taskEditForm.new_task.trim(),
      prompt_template: taskEditForm.prompt_template,
      response_rules: taskEditForm.response_rules,
      output_skeleton: taskEditForm.output_skeleton,
      input_examples: taskEditForm.input_examples,
      output_examples: taskEditForm.output_examples,
    };

    if (!payload.new_task) {
      window.alert("タイトルを入力してください。");
      return;
    }

    try {
      await fetchJsonOrThrow("/api/edit_task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });

      setTasks((previous) =>
        previous.map((task) => {
          if (task.name !== taskEditForm.old_task) return task;
          return {
            ...task,
            name: payload.new_task,
            prompt_template: payload.prompt_template,
            response_rules: payload.response_rules,
            output_skeleton: payload.output_skeleton,
            input_examples: payload.input_examples,
            output_examples: payload.output_examples,
          };
        }),
      );
      invalidateTasksCache();
      closeTaskEditModal();
    } catch (error) {
      window.alert(`更新に失敗しました: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [closeTaskEditModal, taskEditForm]);

  const handlePromptSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isPromptSubmitting) return;

      setIsPromptSubmitting(true);
      setNewPromptStatus({ message: "タスクを追加しています...", variant: "info" });

      try {
        const payload = {
          title: newPromptTitle,
          prompt_content: newPromptContent,
          input_examples: guardrailEnabled ? newPromptInputExample : "",
          output_examples: guardrailEnabled ? newPromptOutputExample : "",
        };

        const { payload: responsePayload } = await fetchJsonOrThrow<{ message?: string }>(
          "/api/add_task",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
          },
          {
            defaultMessage: "タスクの追加に失敗しました。",
          },
        );

        setNewPromptStatus({
          message:
            typeof responsePayload.message === "string" ? responsePayload.message : "タスクが追加されました。",
          variant: "success",
        });

        setNewPromptTitle("");
        setNewPromptContent("");
        setNewPromptInputExample("");
        setNewPromptOutputExample("");
        setGuardrailEnabled(false);

        invalidateTasksCache();
        await refreshTasks(true);

        window.setTimeout(() => {
          closeNewPromptModal();
        }, 550);
      } catch (error) {
        setNewPromptStatus({
          message: error instanceof Error ? error.message : "エラーが発生しました。",
          variant: "error",
        });
        setIsPromptSubmitting(false);
      }
    },
    [
      closeNewPromptModal,
      guardrailEnabled,
      isPromptSubmitting,
      newPromptContent,
      newPromptInputExample,
      newPromptOutputExample,
      newPromptTitle,
      refreshTasks,
    ],
  );

  useEffect(() => {
    void import("../scripts/core/csrf");
    void import("../scripts/components/popup_menu");
    void import("../scripts/components/chat/popup_menu");
    void import("../scripts/components/user_icon");
  }, []);

  useEffect(() => {
    document.body.classList.add("chat-page");
    return () => {
      document.body.classList.remove("chat-page");
      document.body.classList.remove("sidebar-visible");
      document.body.classList.remove("new-prompt-modal-open");
      document.body.style.overflow = "";
    };
  }, []);

  useEffect(() => {
    if (!isChatVisible || !sidebarOpen) {
      document.body.classList.remove("sidebar-visible");
      return;
    }
    document.body.classList.add("sidebar-visible");
  }, [isChatVisible, sidebarOpen]);

  useEffect(() => {
    if (isNewPromptModalOpen) {
      document.body.classList.add("new-prompt-modal-open");
      document.body.style.overflow = "hidden";
      return;
    }

    document.body.classList.remove("new-prompt-modal-open");
    document.body.style.overflow = "";
  }, [isNewPromptModalOpen]);

  useEffect(() => {
    bindSetupViewportFit();
    scheduleSetupViewportFit();
  }, []);

  useEffect(() => {
    if (!isChatVisible) {
      scheduleSetupViewportFit();
    }
  }, [authResolved, isChatVisible, loggedIn, tasks.length, tasksExpanded]);

  useEffect(() => {
    currentRoomIdRef.current = currentRoomId;
  }, [currentRoomId]);

  useEffect(() => {
    const restore = prependScrollRestoreRef.current;
    if (!restore || !chatMessagesRef.current) return;

    const container = chatMessagesRef.current;
    const delta = container.scrollHeight - restore.prevScrollHeight;
    container.scrollTop = restore.prevScrollTop + delta;
    prependScrollRestoreRef.current = null;
  }, [messages]);

  useEffect(() => {
    if (!pendingAutoScrollRef.current) return;
    const container = chatMessagesRef.current;
    if (!container) return;
    pendingAutoScrollRef.current = false;
    container.scrollTop = container.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const applyCachedAuth = consumeAuthSuccessHint();
    const cachedAuthState = readCachedAuthState();
    const canFallback = isCachedAuthStateFresh() && cachedAuthState !== null;

    if (cachedAuthState !== null) {
      setLoggedIn(cachedAuthState);
    }

    if (applyCachedAuth && cachedAuthState === null) {
      setLoggedIn(true);
    }

    let cancelled = false;

    fetch("/api/current_user", { credentials: "same-origin" })
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const nextLoggedIn = Boolean(data?.logged_in);
        writeCachedAuthState(nextLoggedIn);
        setLoggedIn(nextLoggedIn);
      })
      .catch(() => {
        if (cancelled) return;
        if (!canFallback) {
          setLoggedIn(false);
        }
      })
      .finally(() => {
        if (cancelled) return;
        setAuthResolved(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.dispatchEvent(
      new CustomEvent("authstatechange", {
        detail: { loggedIn },
      }),
    );
  }, [loggedIn]);

  useEffect(() => {
    if (!authResolved) return;
    if (!loggedIn && isTaskOrderEditing) {
      setIsTaskOrderEditing(false);
    }
    void refreshTasks(true);
    if (loggedIn) {
      void loadChatRooms();
    } else {
      setChatRooms([]);
    }
  }, [authResolved, isTaskOrderEditing, loadChatRooms, loggedIn, refreshTasks]);

  useEffect(() => {
    if (tasks.length <= 6) {
      setTasksExpanded(false);
    }
  }, [tasks.length]);

  useEffect(() => {
    try {
      const storedRoomId = localStorage.getItem(STORAGE_KEYS.currentChatRoomId);
      if (storedRoomId) {
        setCurrentRoomId(storedRoomId);
        currentRoomIdRef.current = storedRoomId;
      }
    } catch {
      // ignore localStorage failures
    }
  }, []);

  useEffect(() => {
    const onOutsideClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target) return;

      if (modelMenuOpen && modelSelectRef.current && !modelSelectRef.current.contains(target)) {
        setModelMenuOpen(false);
      }

      if (openRoomActionsFor && !target.closest(".room-actions-menu") && !target.closest(".room-actions-icon")) {
        setOpenRoomActionsFor(null);
      }

      if (sidebarOpen && !target.closest(".sidebar") && !target.closest("#sidebar-toggle")) {
        setSidebarOpen(false);
      }
    };

    document.addEventListener("click", onOutsideClick);
    return () => {
      document.removeEventListener("click", onOutsideClick);
    };
  }, [modelMenuOpen, openRoomActionsFor, sidebarOpen]);

  useEffect(() => {
    const onResize = () => {
      setSidebarOpen(false);
      scheduleSetupViewportFit();
    };

    window.addEventListener("resize", onResize);
    window.visualViewport?.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      window.visualViewport?.removeEventListener("resize", onResize);
    };
  }, []);

  useEffect(() => {
    if (!isNewPromptModalOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isPromptSubmitting) return;
      closeNewPromptModal();
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeNewPromptModal, isNewPromptModalOpen, isPromptSubmitting]);

  useEffect(() => {
    if (!shareModalOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeShareModal();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeShareModal, shareModalOpen]);

  useEffect(() => {
    const onCodeCopyClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      const button = target?.closest(".code-block-copy-btn") as HTMLButtonElement | null;
      if (!button) return;

      const codeElement = button.closest(".code-block-container")?.querySelector("code");
      const code = codeElement?.textContent || "";
      const icon = button.querySelector("i");
      const textSpan = button.querySelector("span");
      const defaultLabel = textSpan?.dataset.defaultLabel || textSpan?.textContent || "Copy code";

      if (textSpan) {
        textSpan.dataset.defaultLabel = defaultLabel;
      }

      copyTextToClipboard(code)
        .then(() => {
          if (icon) {
            icon.classList.remove("bi-clipboard", "bi-x-lg");
            icon.classList.add("bi-check-lg");
            window.setTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Copied!";
            window.setTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        })
        .catch(() => {
          if (icon) {
            icon.classList.remove("bi-clipboard", "bi-check-lg");
            icon.classList.add("bi-x-lg");
            window.setTimeout(() => {
              icon.classList.remove("bi-check-lg", "bi-x-lg");
              icon.classList.add("bi-clipboard");
            }, 2000);
          }
          if (textSpan) {
            textSpan.textContent = "Failed";
            window.setTimeout(() => {
              textSpan.textContent = defaultLabel;
            }, 2000);
          }
        });
    };

    document.addEventListener("click", onCodeCopyClick);
    return () => {
      document.removeEventListener("click", onCodeCopyClick);
    };
  }, []);

  useEffect(() => {
    if (promptAssistControllerRef.current) return;
    if (!newPromptAssistRootRef.current) return;
    if (!titleInputRef.current || !contentInputRef.current || !inputExampleRef.current || !outputExampleRef.current) {
      return;
    }

    const controller = initPromptAssist({
      root: newPromptAssistRootRef.current,
      target: "task_modal",
      fields: {
        title: { label: "タイトル", element: titleInputRef.current },
        prompt_content: { label: "プロンプト内容", element: contentInputRef.current },
        input_examples: { label: "入力例", element: inputExampleRef.current },
        output_examples: { label: "出力例", element: outputExampleRef.current },
      },
      beforeApplyField: (fieldName) => {
        if (fieldName === "input_examples" || fieldName === "output_examples") {
          setGuardrailEnabled(true);
        }
      },
    });

    promptAssistControllerRef.current = (controller || null) as PromptAssistController | null;
  }, []);

  useEffect(() => {
    if (newPromptStatus.variant === "error") {
      setNewPromptStatus({ message: "", variant: "info" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPromptTitle, newPromptContent, newPromptInputExample, newPromptOutputExample]);

  const shareXUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent("このチャットルームを共有しました。");
    return `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
  }, [shareUrl]);

  const shareLineUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`;
  }, [shareUrl]);

  const shareFacebookUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
  }, [shareUrl]);

  const supportsNativeShare =
    typeof navigator !== "undefined"
    && typeof (navigator as Navigator & { share?: unknown }).share === "function";

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>ChatCore-AI</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      </Head>

      <div className="chat-page-shell">
        <action-menu></action-menu>

        <div
          id="auth-buttons"
          style={{
            display: loggedIn ? "none" : "flex",
            position: "fixed",
            top: 10,
            right: 10,
            zIndex: 2000,
          }}
        >
          <button id="login-btn" className="auth-btn" onClick={() => {
            window.location.href = "/login";
          }}>
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: loggedIn ? "" : "none" }}></user-icon>

        <div id="setup-container" style={{ display: isChatVisible ? "none" : "block" }}>
          <form className="setup-form" id="setup-form" onSubmit={(event) => event.preventDefault()}>
            <h2 style={{ textAlign: "center", marginBottom: "1.5rem" }}>Chat Core</h2>

            <div className="form-group">
              <label className="form-label">現在の状況・作業環境（入力なしでもOK）</label>
              <textarea
                id="setup-info"
                rows={4}
                placeholder="例：大学生、リモートワーク中　／　自宅のデスク、周囲は静か"
                value={setupInfo}
                onChange={(event) => {
                  setSetupInfo(event.target.value);
                }}
              ></textarea>
            </div>

            <div className="form-group">
              <label className="form-label">AIモデル選択</label>

              <select
                id="ai-model"
                className="model-select-native"
                value={selectedModel}
                onChange={(event) => {
                  setSelectedModel(event.target.value);
                }}
              >
                <option value="openai/gpt-oss-120b">GROQ | GPT-OSS 120B（標準・高品質な応答）</option>
                <option value="gpt-5-mini-2025-08-07">OPENAI | GPT-5 MINI（高品質・推論が必要な作業向け）</option>
                <option value="gemini-2.5-flash">GEMINI | 2.5 FLASH（軽い作業向け）</option>
              </select>

              <div ref={modelSelectRef} className={`model-select ${modelMenuOpen ? "is-open" : ""}`.trim()}>
                <button
                  type="button"
                  className="model-select-trigger"
                  aria-haspopup="listbox"
                  aria-expanded={modelMenuOpen ? "true" : "false"}
                  onClick={() => {
                    setModelMenuOpen((previous) => !previous);
                  }}
                >
                  {selectedModelLabel}
                </button>

                <div className="model-select-menu" role="listbox">
                  <button
                    type="button"
                    className={`model-select-option ${selectedModel === "openai/gpt-oss-120b" ? "is-selected" : ""}`.trim()}
                    role="option"
                    aria-selected={selectedModel === "openai/gpt-oss-120b" ? "true" : "false"}
                    onClick={() => {
                      setSelectedModel("openai/gpt-oss-120b");
                      setModelMenuOpen(false);
                    }}
                  >
                    GROQ | GPT-OSS 120B（標準・高品質な応答）
                  </button>
                  <button
                    type="button"
                    className={`model-select-option ${selectedModel === "gpt-5-mini-2025-08-07" ? "is-selected" : ""}`.trim()}
                    role="option"
                    aria-selected={selectedModel === "gpt-5-mini-2025-08-07" ? "true" : "false"}
                    onClick={() => {
                      setSelectedModel("gpt-5-mini-2025-08-07");
                      setModelMenuOpen(false);
                    }}
                  >
                    OPENAI | GPT-5 MINI（高品質・推論が必要な作業向け）
                  </button>
                  <button
                    type="button"
                    className={`model-select-option ${selectedModel === "gemini-2.5-flash" ? "is-selected" : ""}`.trim()}
                    role="option"
                    aria-selected={selectedModel === "gemini-2.5-flash" ? "true" : "false"}
                    onClick={() => {
                      setSelectedModel("gemini-2.5-flash");
                      setModelMenuOpen(false);
                    }}
                  >
                    GEMINI | 2.5 FLASH（軽い作業向け）
                  </button>
                </div>
              </div>
            </div>

            <div className="task-selection-header">
              <p id="task-selection-text">実行したいタスクを選択（クリックで即実行）</p>

              {loggedIn && (
                <>
                  <button
                    id="edit-task-order-btn"
                    className="primary-button"
                    type="button"
                    data-tooltip={isTaskOrderEditing ? "並び替え編集を終了" : "タスクの並び順を編集"}
                    data-tooltip-placement="bottom"
                    style={{ margin: 0 }}
                    onClick={() => {
                      toggleTaskOrderEditing();
                    }}
                  >
                    <i className={`bi ${isTaskOrderEditing ? "bi-check" : "bi-arrows-move"}`}></i>
                  </button>

                  <button
                    id="openNewPromptModal"
                    className={`circle-button new-prompt-modal-btn ${isNewPromptModalOpen ? "is-rotated" : ""}`.trim()}
                    type="button"
                    data-tooltip="新しいプロンプトを作成"
                    data-tooltip-placement="bottom"
                    onClick={() => {
                      if (isNewPromptModalOpen) {
                        closeNewPromptModal();
                      } else {
                        openNewPromptModal();
                      }
                    }}
                  >
                    <i className="bi bi-plus-lg"></i>
                  </button>
                </>
              )}
            </div>

            <div
              className={`task-selection ${
                tasks.length > 6 ? "tasks-collapsed" : ""
              } ${tasksExpanded || isTaskOrderEditing ? "tasks-expanded" : ""}`.trim()}
              id="task-selection"
            >
              {tasks.map((task, index) => (
                <div
                  key={`${task.name}-${index}`}
                  className={`task-wrapper ${isTaskOrderEditing ? "editable" : ""} ${
                    draggingTaskIndex === index ? "dragging" : ""
                  }`.trim()}
                  draggable={isTaskOrderEditing}
                  onDragStart={(event) => {
                    handleTaskDragStart(event, index);
                  }}
                  onDragOver={(event) => {
                    handleTaskDragOver(event, index);
                  }}
                  onDragEnd={handleTaskDragEnd}
                >
                  <div
                    className={`prompt-card ${isTaskOrderEditing ? "editable" : ""}`.trim()}
                    data-task={task.name}
                    data-prompt_template={task.prompt_template}
                    data-response_rules={task.response_rules}
                    data-output_skeleton={task.output_skeleton}
                    data-input_examples={task.input_examples}
                    data-output_examples={task.output_examples}
                    data-is_default={task.is_default ? "true" : "false"}
                    onClick={() => {
                      if (isTaskOrderEditing) return;
                      void handleTaskCardLaunch(task);
                    }}
                  >
                    {isTaskOrderEditing && (
                      <>
                        <div
                          className="delete-container"
                          style={{
                            position: "absolute",
                            top: "-10px",
                            left: "-10px",
                            zIndex: 10,
                          }}
                        >
                          <button
                            type="button"
                            className="card-delete-btn"
                            style={{
                              width: "24px",
                              height: "24px",
                              borderRadius: "50%",
                              border: "none",
                              color: "white",
                              fontSize: "14px",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                            data-tooltip="このタスクを削除"
                            data-tooltip-placement="top"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleTaskDelete(task.name);
                            }}
                          >
                            <i className="bi bi-trash"></i>
                          </button>
                        </div>

                        <div
                          className="edit-container"
                          style={{
                            position: "absolute",
                            top: "-10px",
                            right: "-10px",
                            zIndex: 10,
                          }}
                        >
                          <button
                            type="button"
                            className="card-edit-btn"
                            style={{
                              width: "24px",
                              height: "24px",
                              borderRadius: "50%",
                              border: "none",
                              color: "white",
                              fontSize: "14px",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                            data-tooltip="このタスクを編集"
                            data-tooltip-placement="top"
                            onClick={(event) => {
                              event.stopPropagation();
                              openTaskEditModal(task);
                            }}
                          >
                            <i className="bi bi-pencil"></i>
                          </button>
                        </div>
                      </>
                    )}

                    <div className="header-container">
                      <div className="task-header">{task.name}</div>
                      <button
                        type="button"
                        className="btn btn-outline-success btn-md task-detail-toggle"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setTaskDetail(task);
                        }}
                      >
                        <i className="bi bi-caret-down"></i>
                      </button>
                    </div>
                  </div>
                </div>
              ))}

              {showTaskToggleButton && (
                <button
                  type="button"
                  id="toggle-tasks-btn"
                  className="primary-button"
                  style={{ width: "100%", marginTop: "0.1rem" }}
                  onClick={() => {
                    setTasksExpanded((previous) => !previous);
                  }}
                >
                  {tasksExpanded ? <i className="bi bi-chevron-up"></i> : <i className="bi bi-chevron-down"></i>} {visibleTaskCountText}
                </button>
              )}
            </div>

            <div style={{ textAlign: "center", marginTop: "0.2rem" }}>
              {loggedIn && (
                <button
                  id="access-chat-btn"
                  type="button"
                  className="primary-button"
                  onClick={() => {
                    void handleAccessChat();
                  }}
                >
                  <i className="bi bi-chat-left-text"></i> これまでのチャットを見る
                </button>
              )}
            </div>
          </form>
        </div>

        <div id="chat-container" style={{ display: isChatVisible ? "flex" : "none" }}>
          <div className="chat-header">
            <div className="header-left">
              <button
                id="back-to-setup"
                className="icon-button"
                data-tooltip="タスク選択に戻る"
                data-tooltip-placement="bottom"
                onClick={() => {
                  showSetupForm();
                }}
              >
                <i className="bi bi-arrow-left"></i>
              </button>
              <span>Chat Core</span>
            </div>
            <div className="header-right">
              <button
                id="share-chat-btn"
                className={`icon-button chat-share-btn ${hasCurrentRoom ? "" : "chat-share-btn--disabled"}`.trim()}
                type="button"
                data-tooltip="このチャットを共有"
                data-tooltip-placement="bottom"
                disabled={!hasCurrentRoom}
                aria-disabled={hasCurrentRoom ? "false" : "true"}
                onClick={() => {
                  if (!hasCurrentRoom) return;
                  openShareModal();
                }}
              >
                <i className="bi bi-share"></i>
              </button>
            </div>
          </div>

          <div className="chat-main">
            <div className={`sidebar ${sidebarOpen ? "open" : ""}`.trim()} id="chat-room-sidebar">
              <button
                id="new-chat-btn"
                className="new-chat-btn"
                onClick={() => {
                  handleNewChat();
                }}
              >
                <i className="bi bi-plus-lg"></i> 新規チャット
              </button>

              <div id="chat-room-list">
                {chatRooms.map((room) => {
                  const roomMenuOpen = openRoomActionsFor === room.id;

                  return (
                    <div
                      key={room.id}
                      className={`chat-room-card ${currentRoomId === room.id ? "active" : ""}`.trim()}
                      onClick={(event) => {
                        const target = event.target as Element;
                        if (target.closest(".room-actions-icon") || target.closest(".room-actions-menu")) {
                          return;
                        }
                        switchChatRoom(room.id);
                      }}
                    >
                      <span>{room.title || "新規チャット"}</span>

                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          position: "relative",
                          marginLeft: "auto",
                        }}
                      >
                        <i
                          className="bi bi-three-dots-vertical room-actions-icon"
                          style={{ cursor: "pointer", fontSize: "18px" }}
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpenRoomActionsFor((previous) => (previous === room.id ? null : room.id));
                          }}
                        ></i>

                        <div className="room-actions-menu" style={{ ...roomMenuBaseStyle, display: roomMenuOpen ? "block" : "none" }}>
                          <div
                            className="menu-item"
                            style={{ ...roomMenuItemBaseStyle, color: "#007bff", background: "#f9f9f9" }}
                            onMouseEnter={(event) => {
                              (event.currentTarget as HTMLDivElement).style.backgroundColor = "#e6f0ff";
                            }}
                            onMouseLeave={(event) => {
                              (event.currentTarget as HTMLDivElement).style.backgroundColor = "#f9f9f9";
                            }}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleRenameRoom(room.id, room.title);
                            }}
                          >
                            <i className="bi bi-pencil-square" style={{ marginRight: "6px" }}></i> 名前変更
                          </div>

                          <div
                            className="menu-item"
                            style={{
                              ...roomMenuItemBaseStyle,
                              color: "#dc3545",
                              background: "#f9f9f9",
                              borderBottom: "none",
                            }}
                            onMouseEnter={(event) => {
                              (event.currentTarget as HTMLDivElement).style.backgroundColor = "#ffe6e6";
                            }}
                            onMouseLeave={(event) => {
                              (event.currentTarget as HTMLDivElement).style.backgroundColor = "#f9f9f9";
                            }}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleDeleteRoom(room.id, room.title);
                            }}
                          >
                            <i className="bi bi-trash" style={{ marginRight: "6px" }}></i> 削除
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="chat-area">
              <button
                id="sidebar-toggle"
                className="icon-button sidebar-toggle chat-sidebar-toggle"
                data-tooltip="チャット一覧を表示"
                data-tooltip-placement="left"
                aria-expanded={sidebarOpen ? "true" : "false"}
                onClick={(event) => {
                  event.stopPropagation();
                  setSidebarOpen((previous) => !previous);
                }}
              >
                <i className="bi bi-arrow-bar-right"></i>
              </button>

              <div className="chat-messages" id="chat-messages" ref={chatMessagesRef} aria-busy={isGenerating ? "true" : undefined}>
                {historyHasMore && historyNextBeforeId !== null && (
                  <button
                    type="button"
                    className="chat-history-load-more-btn"
                    disabled={isLoadingOlder}
                    onClick={() => {
                      void loadOlderChatHistory();
                    }}
                  >
                    {isLoadingOlder ? "読み込み中..." : "過去のメッセージを読み込む"}
                  </button>
                )}

                {messages.map((message) => {
                  if (message.sender === "thinking") {
                    return (
                      <div key={message.id} className="message-wrapper bot-message-wrapper thinking-message-wrapper">
                        <div className="thinking-message" role="status" aria-live="polite" aria-label="AIが応答を準備しています">
                          <ThinkingConstellation />
                        </div>
                      </div>
                    );
                  }

                  if (message.sender === "user") {
                    return (
                      <div key={message.id} className="message-wrapper user-message-wrapper">
                        <div className="user-message" style={{ whiteSpace: "pre-wrap" }}>
                          {message.text}
                        </div>
                        <div className="message-actions">
                          <CopyActionButton
                            getText={() => {
                              return message.text;
                            }}
                          />
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div
                      key={message.id}
                      className={`message-wrapper bot-message-wrapper ${message.streaming ? "message-wrapper--streaming" : ""}`.trim()}
                    >
                      <div className={`bot-message ${message.streaming ? "bot-message--streaming" : ""}`.trim()}>
                        <BotMessageHtml text={message.text} />
                      </div>
                      {!message.streaming && (
                        <div className="message-actions">
                          <CopyActionButton
                            getText={() => {
                              return message.text;
                            }}
                          />
                          {!message.error && (
                            <MemoSaveActionButton
                              getText={() => {
                                return message.text;
                              }}
                            />
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="input-container">
                <div className="input-wrapper">
                  <input
                    type="text"
                    id="user-input"
                    placeholder="メッセージを入力..."
                    value={chatInput}
                    onChange={(event) => {
                      setChatInput(event.target.value);
                    }}
                    onKeyDown={handleChatInputKeyDown}
                  />
                  <button
                    type="button"
                    id="send-btn"
                    className={isGenerating ? "send-btn--stop" : ""}
                    aria-label={isGenerating ? "停止" : "送信"}
                    data-tooltip={isGenerating ? "生成を停止" : "メッセージを送信"}
                    data-tooltip-placement="top"
                    onClick={() => {
                      handleSendMessage();
                    }}
                  >
                    <i className={`bi ${isGenerating ? "bi-stop-fill" : "bi-send"}`}></i>
                  </button>
                </div>
              </div>

              <chat-action-menu></chat-action-menu>
            </div>
          </div>
        </div>

        <div
          id="io-modal"
          style={{ display: taskDetail ? "flex" : "none" }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="taskDetailTitle"
          aria-hidden={taskDetail ? "false" : "true"}
          tabIndex={-1}
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setTaskDetail(null);
            }
          }}
        >
          <div className="io-modal-content" id="io-modal-content" onClick={(event) => {
            event.stopPropagation();
          }}>
            {taskDetail && (
              <div className="task-detail-modal-shell">
                <div className="task-detail-modal-header">
                  <div>
                    <p className="task-detail-modal-eyebrow">Task Detail</p>
                    <h5 className="task-detail-modal-title" id="taskDetailTitle">
                      タスク詳細
                    </h5>
                  </div>
                  <button
                    type="button"
                    className="task-detail-modal-close"
                    data-close-task-detail
                    aria-label="タスク詳細を閉じる"
                    onClick={() => {
                      setTaskDetail(null);
                    }}
                  >
                    <i className="bi bi-x-lg"></i>
                  </button>
                </div>

                <div className="task-detail-sections">
                  <section className="task-detail-section">
                    <h6 className="task-detail-section-title">タスク名</h6>
                    <div className="task-detail-section-body task-detail-section-body-compact">{taskDetail.name}</div>
                  </section>

                  <section className="task-detail-section">
                    <h6 className="task-detail-section-title">プロンプトテンプレート</h6>
                    <div
                      className="task-detail-section-body"
                      dangerouslySetInnerHTML={{
                        __html: formatMultilineHtml(taskDetail.prompt_template),
                      }}
                    ></div>
                  </section>

                  {taskDetail.response_rules && (
                    <section className="task-detail-section">
                      <h6 className="task-detail-section-title">回答ルール</h6>
                      <div
                        className="task-detail-section-body"
                        dangerouslySetInnerHTML={{
                          __html: formatMultilineHtml(taskDetail.response_rules),
                        }}
                      ></div>
                    </section>
                  )}

                  {taskDetail.output_skeleton && (
                    <section className="task-detail-section">
                      <h6 className="task-detail-section-title">出力テンプレート</h6>
                      <div
                        className="task-detail-section-body"
                        dangerouslySetInnerHTML={{
                          __html: formatMultilineHtml(taskDetail.output_skeleton),
                        }}
                      ></div>
                    </section>
                  )}

                  {taskDetail.input_examples && (
                    <section className="task-detail-section">
                      <h6 className="task-detail-section-title">入力例</h6>
                      <div
                        className="task-detail-section-body"
                        dangerouslySetInnerHTML={{
                          __html: formatMultilineHtml(taskDetail.input_examples),
                        }}
                      ></div>
                    </section>
                  )}

                  {taskDetail.output_examples && (
                    <section className="task-detail-section">
                      <h6 className="task-detail-section-title">出力例</h6>
                      <div
                        className="task-detail-section-body"
                        dangerouslySetInnerHTML={{
                          __html: formatMultilineHtml(taskDetail.output_examples),
                        }}
                      ></div>
                    </section>
                  )}

                  {!taskDetail.response_rules &&
                    !taskDetail.output_skeleton &&
                    !taskDetail.input_examples &&
                    !taskDetail.output_examples && (
                      <section className="task-detail-section">
                        <h6 className="task-detail-section-title">補助情報</h6>
                        <div className="task-detail-section-body">
                          追加の回答ルールや例は設定されていません。
                        </div>
                      </section>
                    )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div id="newPromptModal" className={`new-prompt-modal ${isNewPromptModalOpen ? "show" : ""}`.trim()} style={{ display: isNewPromptModalOpen ? "flex" : "none" }} onClick={(event) => {
          if (event.target === event.currentTarget && !isPromptSubmitting) {
            closeNewPromptModal();
          }
        }}>
          <div className="new-prompt-modal-content">
            <button
              type="button"
              className="new-modal-close-btn"
              id="newModalCloseBtn"
              aria-label="モーダルを閉じる"
              onClick={() => {
                if (isPromptSubmitting) return;
                closeNewPromptModal();
              }}
            >
              &times;
            </button>

            <div className="new-prompt-modal__hero">
              <div className="new-prompt-modal__hero-copy">
                <p className="new-prompt-modal__eyebrow">Prompt Composer</p>
                <h2>新しいプロンプトを追加</h2>
                <p className="new-prompt-modal__lead">AI 補助を使いながら、短時間で実用的なタスクに整えられます。</p>
              </div>
              <div className="new-prompt-modal__hero-badges" aria-hidden="true">
                <span>Draft</span>
                <span>Polish</span>
                <span>Examples</span>
              </div>
            </div>

            <form className="new-post-form" id="newPostForm" onSubmit={(event) => {
              void handlePromptSubmit(event);
            }}>
              <div className="form-group">
                <label htmlFor="new-prompt-title">タイトル</label>
                <input
                  ref={titleInputRef}
                  type="text"
                  id="new-prompt-title"
                  placeholder="プロンプトのタイトルを入力"
                  required
                  value={newPromptTitle}
                  onChange={(event) => {
                    setNewPromptTitle(event.target.value);
                  }}
                />
              </div>

              <div className="form-group">
                <label htmlFor="new-prompt-content">プロンプト内容</label>
                <textarea
                  ref={contentInputRef}
                  id="new-prompt-content"
                  rows={5}
                  placeholder="具体的なプロンプト内容を入力"
                  required
                  value={newPromptContent}
                  onChange={(event) => {
                    setNewPromptContent(event.target.value);
                  }}
                ></textarea>
              </div>

              <div id="newPromptAssistRoot" ref={newPromptAssistRootRef}></div>
              <p
                id="newPromptSubmitStatus"
                className="composer-status"
                hidden={!newPromptStatus.message}
                data-variant={newPromptStatus.variant}
              >
                {newPromptStatus.message}
              </p>

              <div className="form-group form-group--toggle">
                <label className="composer-toggle" htmlFor="new-guardrail-checkbox">
                  <input
                    type="checkbox"
                    id="new-guardrail-checkbox"
                    checked={guardrailEnabled}
                    onChange={(event) => {
                      setGuardrailEnabled(event.target.checked);
                    }}
                  />
                  <span className="composer-toggle__copy">
                    <strong>入出力例を追加する</strong>
                    <small>AI 提案の再現性を高めるための例を持たせます。</small>
                  </span>
                </label>
              </div>

              <div id="new-guardrail-fields" style={{ display: guardrailEnabled ? "block" : "none" }}>
                <div className="form-group">
                  <label htmlFor="new-prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
                  <textarea
                    ref={inputExampleRef}
                    id="new-prompt-input-example"
                    rows={3}
                    placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
                    value={newPromptInputExample}
                    onChange={(event) => {
                      setNewPromptInputExample(event.target.value);
                    }}
                  ></textarea>
                </div>
                <div className="form-group">
                  <label htmlFor="new-prompt-output-example">出力例</label>
                  <textarea
                    ref={outputExampleRef}
                    id="new-prompt-output-example"
                    rows={3}
                    placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました..."
                    value={newPromptOutputExample}
                    onChange={(event) => {
                      setNewPromptOutputExample(event.target.value);
                    }}
                  ></textarea>
                </div>
              </div>

              <button type="submit" className="submit-btn" disabled={isPromptSubmitting}>
                {isPromptSubmitting ? (
                  <>
                    <i className="bi bi-stars"></i> AIと投稿を準備中...
                  </>
                ) : (
                  <>
                    <i className="bi bi-upload"></i> 投稿する
                  </>
                )}
              </button>
            </form>
          </div>
        </div>

        <div id="taskEditModal" className="custom-modal" style={{ display: taskEditModalOpen ? "flex" : "none" }}>
          <div className="custom-modal-dialog">
            <div className="custom-modal-content">
              <div className="custom-modal-header">
                <h5 className="custom-modal-title">タスク編集</h5>
                <button
                  type="button"
                  className="custom-modal-close"
                  id="closeTaskEditModal"
                  onClick={closeTaskEditModal}
                >
                  ×
                </button>
              </div>

              <div className="custom-modal-body">
                <form id="taskEditForm" onSubmit={(event) => event.preventDefault()}>
                  <div className="custom-form-group">
                    <label htmlFor="taskName" className="custom-form-label">
                      <span style={{ color: "green" }}>タイトル</span>
                    </label>
                    <input
                      type="text"
                      className="custom-form-control"
                      id="taskName"
                      name="name"
                      placeholder="例：メール作成"
                      value={taskEditForm.new_task}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          new_task: event.target.value,
                        }));
                      }}
                    />
                    <div className="custom-form-text">タスクの名前を入力してください。</div>
                  </div>

                  <div className="custom-form-group">
                    <label htmlFor="promptTemplate" className="custom-form-label">
                      <span style={{ color: "green" }}>プロンプトテンプレート</span>
                    </label>
                    <textarea
                      className="custom-form-control"
                      id="promptTemplate"
                      name="prompt_template"
                      rows={2}
                      placeholder="例：メール本文の書き出し..."
                      value={taskEditForm.prompt_template}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          prompt_template: event.target.value,
                        }));
                      }}
                    ></textarea>
                    <div className="custom-form-text">タスク実行時に使用するプロンプトテンプレートです。</div>
                  </div>

                  <div className="custom-form-group">
                    <label htmlFor="responseRules" className="custom-form-label">
                      <span style={{ color: "green" }}>回答ルール</span>
                    </label>
                    <textarea
                      className="custom-form-control"
                      id="responseRules"
                      name="response_rules"
                      rows={2}
                      placeholder="例：不足情報があれば先に確認する。結論から先に書く。"
                      value={taskEditForm.response_rules}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          response_rules: event.target.value,
                        }));
                      }}
                    ></textarea>
                    <div className="custom-form-text">回答時に優先させたいルールを任意で指定します。</div>
                  </div>

                  <div className="custom-form-group">
                    <label htmlFor="outputSkeleton" className="custom-form-label">
                      <span style={{ color: "green" }}>出力テンプレート</span>
                    </label>
                    <textarea
                      className="custom-form-control"
                      id="outputSkeleton"
                      name="output_skeleton"
                      rows={2}
                      placeholder={"例：## 結論\n## 詳細\n## 次の一手"}
                      value={taskEditForm.output_skeleton}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          output_skeleton: event.target.value,
                        }));
                      }}
                    ></textarea>
                    <div className="custom-form-text">回答の骨組みを任意で指定します。</div>
                  </div>

                  <div className="custom-form-group">
                    <label htmlFor="inputExamples" className="custom-form-label">
                      <span style={{ color: "green" }}>入力例</span>
                    </label>
                    <textarea
                      className="custom-form-control"
                      id="inputExamples"
                      name="input_examples"
                      rows={2}
                      placeholder="例：今日の天気は？"
                      value={taskEditForm.input_examples}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          input_examples: event.target.value,
                        }));
                      }}
                    ></textarea>
                    <div className="custom-form-text">ユーザーが入力する例です。</div>
                  </div>

                  <div className="custom-form-group">
                    <label htmlFor="outputExamples" className="custom-form-label">
                      <span style={{ color: "green" }}>出力例</span>
                    </label>
                    <textarea
                      className="custom-form-control"
                      id="outputExamples"
                      name="output_examples"
                      rows={2}
                      placeholder="例：晴れです。"
                      value={taskEditForm.output_examples}
                      onChange={(event) => {
                        setTaskEditForm((previous) => ({
                          ...previous,
                          output_examples: event.target.value,
                        }));
                      }}
                    ></textarea>
                    <div className="custom-form-text">タスク実行時の出力例です。</div>
                  </div>
                </form>
              </div>

              <div className="custom-modal-footer">
                <button
                  type="button"
                  className="custom-btn-secondary"
                  id="cancelTaskEditModal"
                  onClick={closeTaskEditModal}
                >
                  キャンセル
                </button>
                <button
                  type="button"
                  className="custom-btn-primary"
                  id="saveTaskChanges"
                  onClick={() => {
                    void handleTaskEditSave();
                  }}
                >
                  保存
                </button>
              </div>
            </div>
          </div>
        </div>

        <div
          id="chat-share-modal"
          className="chat-share-modal"
          role="dialog"
          aria-modal="true"
          aria-hidden={shareModalOpen ? "false" : "true"}
          aria-labelledby="chat-share-title"
          style={{ display: shareModalOpen ? "flex" : "none" }}
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeShareModal();
            }
          }}
        >
          <div className="chat-share-modal__content">
            <div className="chat-share-modal__header">
              <h5 id="chat-share-title">チャットを共有</h5>
              <button
                type="button"
                id="chat-share-close-btn"
                className="chat-share-close-btn"
                aria-label="共有モーダルを閉じる"
                onClick={closeShareModal}
              >
                <i className="bi bi-x-lg"></i>
              </button>
            </div>

            <p className="chat-share-modal__desc">
              共有リンクを作成すると、このチャットルームの履歴をURL経由で閲覧できます。
            </p>

            <div className="chat-share-link-row">
              <input
                type="text"
                id="chat-share-link-input"
                readOnly
                placeholder="共有リンクを準備しています"
                value={shareUrl}
              />
            </div>

            <p id="chat-share-status" className={`chat-share-status ${shareStatus.error ? "chat-share-status--error" : ""}`.trim()}>
              {shareStatus.message}
            </p>

            <div className="chat-share-actions">
              <button
                type="button"
                id="chat-share-copy-btn"
                className="primary-button chat-share-icon-btn"
                aria-label="リンクをコピー"
                title="リンクをコピー"
                disabled={shareLoading}
                onClick={() => {
                  void copyShareLink();
                }}
              >
                <i className="bi bi-files" aria-hidden="true"></i>
              </button>
              <button
                type="button"
                id="chat-share-web-btn"
                className="primary-button chat-share-icon-btn"
                aria-label="端末で共有"
                title="端末で共有"
                disabled={shareLoading}
                onClick={() => {
                  void shareWithNativeSheet();
                }}
                style={{ display: supportsNativeShare ? "inline-flex" : "none" }}
              >
                <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
              </button>
            </div>

            <div className="chat-share-sns">
              <a id="chat-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareXUrl}>
                <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                  ></path>
                </svg>
                <span>X</span>
              </a>
              <a id="chat-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareLineUrl}>
                <i className="bi bi-chat-dots"></i>
                <span>LINE</span>
              </a>
              <a
                id="chat-share-sns-facebook"
                target="_blank"
                rel="noopener noreferrer"
                href={shareFacebookUrl}
              >
                <i className="bi bi-facebook"></i>
                <span>Facebook</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
