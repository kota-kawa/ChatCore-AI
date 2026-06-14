import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MutableRefObject,
} from "react";
import { List, useDynamicRowHeight, type ListImperativeAPI } from "react-window";

import { InlineLoading } from "../ui/inline_loading";
import { MAX_CHAT_MESSAGE_LENGTH } from "../../lib/chat_page/constants";
import { parseTaskLaunchMessage } from "../../lib/chat_page/task_utils";
import type { NormalizedTask, UiChatMessage } from "../../lib/chat_page/types";
import { stripWebSearchSourcesHtml } from "../../scripts/chat/message_utils";
import { BotMessageParts } from "./bot_message_parts";
import { BranchNavigator } from "./branch_navigator";
import { CopyActionButton } from "./copy_action_button";
import { EditActionButton } from "./edit_action_button";
import { MemoSaveActionButton } from "./memo_save_action_button";
import { RegenerateActionButton } from "./regenerate_action_button";
import { TaskPromptDisclosure } from "./task_prompt_disclosure";
import { ThinkingConstellation } from "./thinking_constellation";
import { UserMessageHtml } from "./user_message_html";

// SSR 環境では useLayoutEffect が警告を出すため、ブラウザ上でのみ useLayoutEffect を使う。
// Use useLayoutEffect on the browser to avoid React SSR warnings.
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

// ユーザーメッセージのインライン編集フォーム。送信すると再生成をトリガーする。
// Inline edit form for a user message; submitting triggers message regeneration.
function UserMessageEditForm({
  initialText,
  onSubmit,
  onCancel,
}: {
  initialText: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(initialText);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // マウント直後にフォーカスを当て、カーソルを末尾へ移動し、テキスト量に合わせて高さを調整する。
  // On mount: focus the textarea, move cursor to end, and auto-size height to content.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, []);

  // IME 確定中の Enter による誤送信を防ぎ、Escape でキャンセル、Enter（Shift なし）で送信する。
  // Prevent accidental submit during IME composition; Escape cancels, bare Enter submits.
  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (event.nativeEvent.isComposing) return;
      if (event.key === "Escape") {
        onCancel();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const trimmed = text.trim();
        if (trimmed && trimmed.length <= MAX_CHAT_MESSAGE_LENGTH) {
          onSubmit(trimmed);
        }
      }
    },
    [onCancel, onSubmit, text],
  );

  // テキスト変更のたびに textarea の高さを内容に合わせて伸縮させる（最大 240px）。
  // Auto-resize textarea height to match content on every change (capped at 240px).
  const handleChange = useCallback((event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(event.target.value);
    const el = event.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, []);

  // 空文字または文字数上限超過の場合は送信ボタンを無効化する。
  // Disable submit when text is empty or exceeds the max message length.
  const trimmed = text.trim();
  const canSubmit = trimmed.length > 0 && trimmed.length <= MAX_CHAT_MESSAGE_LENGTH;

  return (
    <div className="user-message-edit-form">
      <textarea
        ref={textareaRef}
        className="user-message-edit-textarea"
        value={text}
        rows={1}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
      />
      <div className="user-message-edit-actions">
        <button type="button" className="user-message-edit-cancel" onClick={onCancel}>
          <i className="bi bi-x-lg" aria-hidden="true"></i>
          キャンセル
        </button>
        <button
          type="button"
          className="user-message-edit-submit"
          disabled={!canSubmit}
          onClick={() => {
            if (canSubmit) onSubmit(trimmed);
          }}
        >
          <i className="bi bi-arrow-clockwise" aria-hidden="true"></i>
          再生成
        </button>
      </div>
    </div>
  );
}

// 仮想リスト上の各行を表す型。「もっと読む」ボタン行とメッセージ行の 2 種類がある。
// Discriminated union for virtual list rows: a load-more trigger or a chat message.
type ChatMessageListRow =
  | { kind: "load-more" }
  | { kind: "message"; message: UiChatMessage };

// ChatMessageRow に渡す共有プロパティ群。react-window の rowProps 経由で全行に届く。
// Shared props passed to every ChatMessageRow via react-window's rowProps mechanism.
type ChatMessageRowProps = {
  rows: ChatMessageListRow[];
  isGenerating: boolean;
  isLoadingOlder: boolean;
  loadOlderChatHistory: () => Promise<void>;
  onRegenerate: () => void;
  editingMessageId: string | null;
  onEditStart: (messageId: string) => void;
  onEditCancel: () => void;
  onEditAndRegenerate: (newMessage: string, trailingUserCount: number) => void;
  onSwitchBranch: (messageId: number) => void;
  taskLookup: Map<string, NormalizedTask>;
};

// react-window が行コンポーネントに渡す追加プロパティ（位置・サイズ・aria 属性）。
// Additional props injected by react-window per row: position, size, and ARIA attributes.
type ChatMessageRowComponentProps = ChatMessageRowProps & {
  ariaAttributes: {
    "aria-posinset": number;
    "aria-setsize": number;
    role: "listitem";
  };
  index: number;
  style: CSSProperties;
};

// 仮想リストの 1 行を描画するコンポーネント。行の種別（ロード・思考中・ユーザー・アシスタント）
// に応じて適切な UI を返す。
// Renders a single virtual list row, branching on row kind and message sender.
function ChatMessageRow({
  ariaAttributes,
  index,
  isGenerating,
  isLoadingOlder,
  loadOlderChatHistory,
  onRegenerate,
  editingMessageId,
  onEditStart,
  onEditCancel,
  onEditAndRegenerate,
  onSwitchBranch,
  rows,
  style,
  taskLookup,
}: ChatMessageRowComponentProps) {
  const row = rows[index];
  // 先頭・末尾・ロード行にそれぞれ専用クラスを付与してスタイリングを切り替える。
  // Apply positional and kind-specific CSS modifier classes for styling.
  const rowClassName = [
    "chat-message-row",
    index === 0 ? "chat-message-row--first" : "",
    index === rows.length - 1 ? "chat-message-row--last" : "",
    row?.kind === "load-more" ? "chat-message-row--history" : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (!row) {
    return <div {...ariaAttributes} className={rowClassName} style={style}></div>;
  }

  // 過去メッセージが存在する場合に「もっと読む」ボタン行を表示する。
  // Show a "load more" row when older chat history is available.
  if (row.kind === "load-more") {
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <button
          type="button"
          className="chat-history-load-more-btn"
          disabled={isLoadingOlder}
          onClick={() => {
            void loadOlderChatHistory();
          }}
        >
          {isLoadingOlder ? <InlineLoading label="読み込み中" /> : "過去のメッセージを読み込む"}
        </button>
      </div>
    );
  }

  const { message } = row;
  // AI が応答を生成中であることを視覚的にアニメーションで示す思考中インジケーター。
  // Thinking indicator shown while the AI is preparing its response, with accessibility live region.
  if (message.sender === "thinking") {
    const statusText = message.text.trim() || "AIが応答を準備しています";
    const generationPhase = message.generationPhase ?? "preparing";
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper bot-message-wrapper thinking-message-wrapper">
          <div
            className="thinking-message"
            data-generation-phase={generationPhase}
            role="status"
            aria-live="polite"
            aria-label={statusText}
          >
            <ThinkingConstellation phase={generationPhase} />
            <span className="thinking-message__status">{statusText}</span>
          </div>
        </div>
      </div>
    );
  }

  if (message.sender === "user") {
    // launch-preview-user はチャット起動中に仮表示するプレースホルダーで、編集対象外。
    // launch-preview-user is a placeholder shown during chat launch; it cannot be edited.
    const isLaunchPreview = message.id === "launch-preview-user";
    const isEditing = editingMessageId === message.id;

    if (!isLaunchPreview && isEditing) {
      // 現在の行より後ろに続くユーザーメッセージ数を数え、再生成時の削除範囲を決定する。
      // Count trailing user messages after this row to determine regeneration scope.
      const trailingUserCount = rows
        .slice(index + 1)
        .filter((r) => r.kind === "message" && r.message.sender === "user").length;
      return (
        <div {...ariaAttributes} className={rowClassName} style={style}>
          <div className="message-wrapper user-message-wrapper">
            <UserMessageEditForm
              initialText={message.text}
              onSubmit={(text) => {
                onEditAndRegenerate(text, trailingUserCount);
                onEditCancel();
              }}
              onCancel={onEditCancel}
            />
          </div>
        </div>
      );
    }

    // 生成中または別のメッセージ編集中は編集ボタンを無効化する。
    // Disable editing while the AI is generating or another message is being edited.
    const isEditDisabled = isGenerating || editingMessageId !== null;
    const taskLaunch = parseTaskLaunchMessage(message.text);
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper user-message-wrapper">
          <div
            className={`user-message${taskLaunch ? " user-message--task-launch" : ""}`}
          >
            {/* 【タスク】名と【状況・作業環境】は折り畳みの外に常時表示する。 */}
            {/* The task name and setup input always stay visible (outside the disclosure). */}
            <UserMessageHtml text={message.text} attachedFileNames={message.attachedFileNames} />
            {taskLaunch ? <TaskPromptDisclosure task={taskLookup.get(taskLaunch.taskName)} /> : null}
          </div>
          {isLaunchPreview ? (
            // プレースホルダー行ではアクションボタン領域をレイアウト確保のため非表示で保持する。
            // Reserve action button space invisibly for placeholder rows to maintain layout.
            <div className="message-actions" style={{ visibility: "hidden" }}>
              <div className="copy-btn"><i className="bi bi-clipboard"></i></div>
            </div>
          ) : (
            <div className="message-actions">
              <BranchNavigator
                message={message}
                disabled={isGenerating}
                onSwitchBranch={onSwitchBranch}
              />
              <EditActionButton
                onEdit={() => {
                  onEditStart(message.id);
                }}
                disabled={isEditDisabled}
              />
              <CopyActionButton
                getText={() => {
                  return message.text;
                }}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  // 直後にアシスタントメッセージが無い場合のみ再生成ボタンを表示する。
  // Show the regenerate button only on the last assistant message in the list.
  const isLastAssistantMessage =
    message.sender === "assistant" &&
    !rows.slice(index + 1).some((r) => r.kind === "message" && r.message.sender === "assistant");
  // ストリーミング中はアクションボタンを非表示にして誤操作を防ぐ。
  // Hide action buttons during active streaming to prevent accidental interactions.
  const isActivelyStreaming = Boolean(message.streaming && isGenerating);
  const actionVisibilityStyle = isActivelyStreaming ? { visibility: "hidden" as const } : undefined;

  return (
    <div {...ariaAttributes} className={rowClassName} style={style}>
      <div
        className={`message-wrapper bot-message-wrapper ${isActivelyStreaming ? "message-wrapper--streaming" : ""}`.trim()}
      >
        <div className={`bot-message ${isActivelyStreaming ? "bot-message--streaming" : ""}`.trim()}>
          <BotMessageParts fallbackText={message.text} parts={message.parts} />
        </div>
        <div className="message-actions" style={actionVisibilityStyle}>
          {!message.error && (
            <BranchNavigator
              message={message}
              disabled={isGenerating}
              onSwitchBranch={onSwitchBranch}
            />
          )}
          <CopyActionButton
            getText={() => {
              return message.text;
            }}
          />
          {!message.error && (
            // メモ保存前に Web 検索ソースの HTML タグを除去してプレーンテキストにする。
            // Strip web search source HTML before saving to memo for clean plain text.
            <MemoSaveActionButton
              getText={() => {
                return stripWebSearchSourcesHtml(message.text);
              }}
            />
          )}
          {!message.error && isLastAssistantMessage && (
            <RegenerateActionButton
              onRegenerate={onRegenerate}
              disabled={isGenerating}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ChatMessageList が受け取る公開 Props の型定義。
// Public prop types for the ChatMessageList component.
type ChatMessageListProps = {
  chatMessagesRef: MutableRefObject<HTMLDivElement | null>;
  currentRoomId: string | null;
  setupInfo?: string;
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isChatLaunching: boolean;
  isGenerating: boolean;
  isLoadingOlder: boolean;
  launchingTaskName: string | null;
  loadOlderChatHistory: () => Promise<void>;
  messages: UiChatMessage[];
  onRegenerate: () => void;
  onEditAndRegenerate: (newMessage: string, trailingUserCount: number) => void;
  onSwitchBranch: (messageId: number) => void;
  tasks: NormalizedTask[];
};

// react-window による仮想スクロールでチャットメッセージを描画する本体コンポーネント。
// Core component that renders chat messages in a react-window virtual scroll list.
function ChatMessageListComponent({
  chatMessagesRef,
  currentRoomId,
  setupInfo,
  historyHasMore,
  historyNextBeforeId,
  isChatLaunching,
  isGenerating,
  isLoadingOlder,
  launchingTaskName,
  loadOlderChatHistory,
  messages,
  onRegenerate,
  onEditAndRegenerate,
  onSwitchBranch,
  tasks,
}: ChatMessageListProps) {
  // 同時に編集できるメッセージは 1 件のみ。null は非編集状態を表す。
  // Only one message can be in edit mode at a time; null means no active edit.
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);

  const handleEditStart = useCallback((messageId: string) => {
    setEditingMessageId(messageId);
  }, []);

  const handleEditCancel = useCallback(() => {
    setEditingMessageId(null);
  }, []);

  // タスク名から定義を引くための索引。履歴から読み込んだメッセージは本文しか持たないため、
  // 表示中のタスク一覧と突き合わせて裏側のプロンプトを復元する。
  // Index task definitions by name so history-loaded messages (text only) can be matched
  // back to their underlying prompt.
  const taskLookup = useMemo(() => {
    const lookup = new Map<string, NormalizedTask>();
    tasks.forEach((task) => {
      lookup.set(task.name, task);
    });
    return lookup;
  }, [tasks]);

  // 動的行高を計測・管理する。roomId が変わると計測キャッシュをリセットする。
  // Track dynamic row heights; reset cache when the room changes.
  const rowHeight = useDynamicRowHeight({
    defaultRowHeight: 104,
    key: currentRoomId || "no-room",
  });
  const listApiRef = useRef<ListImperativeAPI | null>(null);

  // react-window の List API と DOM 要素を両方の ref に紐付けて外部から参照できるようにする。
  // Bind both the virtual list API and its DOM element to refs for external scroll control.
  const setListRef = useCallback(
    (api: ListImperativeAPI | null) => {
      listApiRef.current = api;
      chatMessagesRef.current = api?.element ?? null;
    },
    [chatMessagesRef],
  );

  // 「もっと読む」行と実際のメッセージ行を結合して仮想リストに渡す行配列を構築する。
  // チャット起動中かつメッセージがない場合はプレースホルダー行を差し込む。
  // Build the row array for the virtual list, prepending a load-more entry when needed.
  // During chat launch with no messages yet, inject placeholder rows instead.
  const rows = useMemo<ChatMessageListRow[]>(() => {
    const nextRows: ChatMessageListRow[] = [];
    if (historyHasMore && historyNextBeforeId !== null) {
      nextRows.push({ kind: "load-more" });
    }

    const visibleMessages =
      isChatLaunching && messages.length === 0
        ? [
            {
              id: "launch-preview-user",
              sender: "user" as const,
              text: launchingTaskName
                ? [
                    `【タスク】${launchingTaskName}`,
                    setupInfo?.trim() ? `【状況・作業環境】${setupInfo.trim()}` : "",
                  ]
                    .filter(Boolean)
                    .join("\n")
                : setupInfo?.trim() || "チャットを準備しています...",
            },
            {
              id: "launch-preview-thinking",
              sender: "thinking" as const,
              text: "AIが応答を準備しています",
            },
          ]
        : messages;

    visibleMessages.forEach((message) => {
      nextRows.push({ kind: "message", message });
    });
    return nextRows;
  }, [historyHasMore, historyNextBeforeId, isChatLaunching, launchingTaskName, messages, setupInfo]);

  // rowProps をメモ化することで、rows や状態が変わらない限り各行の再レンダリングを防ぐ。
  // Memoize rowProps to prevent unnecessary re-renders of individual rows.
  const rowProps = useMemo<ChatMessageRowProps>(
    () => ({
      rows,
      isGenerating,
      isLoadingOlder,
      loadOlderChatHistory,
      onRegenerate,
      editingMessageId,
      onEditStart: handleEditStart,
      onEditCancel: handleEditCancel,
      onEditAndRegenerate,
      onSwitchBranch,
      taskLookup,
    }),
    [
      rows,
      isGenerating,
      isLoadingOlder,
      loadOlderChatHistory,
      onRegenerate,
      editingMessageId,
      handleEditStart,
      handleEditCancel,
      onEditAndRegenerate,
      onSwitchBranch,
      taskLookup,
    ],
  );

  // 最後のメッセージが思考中か、起動中なら末尾スクロールを追従させる必要がある。
  // Auto-scroll to bottom is needed when the AI is actively thinking or chat is launching.
  const shouldRevealThinking = isChatLaunching || messages[messages.length - 1]?.sender === "thinking";
  const hasPerformedInitialScrollRef = useRef(false);
  // 初回マウント直後は react-window が動的行高を計測する数フレームで scrollTop が
  // 補正されることがあるため、その「ガタつき」を利用者から隠す目的で
  // メッセージ一覧自体を一瞬だけ不可視にしておき、末尾アンカリングが落ち着いてから
  // フェードインさせる。アンカリングが終わるまでの 80ms ほどを目安にする。
  // Hide the list briefly on first mount to mask the scroll-position jitter that occurs
  // while react-window measures dynamic row heights over several frames (~80ms).
  const [isInitialContentRevealed, setIsInitialContentRevealed] = useState(false);

  // 仮想リストの末尾へスクロールする。List API が使えない場合は DOM を直接操作する。
  // Scroll to the last row using the virtual list API, falling back to direct DOM scroll.
  const scrollListToEnd = useCallback(() => {
    const listApi = listApiRef.current;
    const listElement = chatMessagesRef.current;

    if (listApi && rows.length > 0) {
      try {
        listApi.scrollToRow({ index: rows.length - 1, align: "end", behavior: "instant" });
        return;
      } catch {
        // Fall through to direct DOM scrolling if the virtual list is between renders.
      }
    }

    if (listElement) {
      listElement.scrollTop = listElement.scrollHeight;
    }
  }, [chatMessagesRef, rows.length]);

  const scrollThinkingIntoView = scrollListToEnd;

  // リストの高さが変わった際（キーボード表示など）、思考中なら末尾を追従させる。
  // Re-anchor to the bottom on list resize (e.g. virtual keyboard appearing) when thinking.
  const handleListResize = useCallback(() => {
    if (!shouldRevealThinking || typeof window === "undefined") return;
    window.requestAnimationFrame(scrollThinkingIntoView);
  }, [scrollThinkingIntoView, shouldRevealThinking]);

  // 初回マウント（room 切替や「これまでのチャットを見る」押下時）で、ユーザーがチャットの
  // 一番上を一瞬見てから一番下にスクロールするのを避けるため、paint 前に末尾へ位置合わせする。
  // react-window の動的行高計測がフレームをまたいで進むため、追加フレームでも再調整する。
  // その間は [isInitialContentRevealed=false] で一覧自体を不可視にしておき、
  // 末尾アンカリングが完了してから表示する。
  // On initial mount (room switch or "view history" press), scroll to the bottom before paint
  // so users never see the top of the list flash by. Re-scroll over multiple frames while
  // react-window settles dynamic row heights, then reveal the list.
  useIsomorphicLayoutEffect(() => {
    if (hasPerformedInitialScrollRef.current) return;
    if (rows.length === 0) {
      // 表示する行が無い場合は隠す必要が無いので、空状態をそのまま見せる。
      // No rows to anchor — reveal immediately without hiding.
      setIsInitialContentRevealed(true);
      return;
    }

    hasPerformedInitialScrollRef.current = true;

    scrollListToEnd();

    // 内容がビューポートに収まりスクロール補正が起こり得ない場合（新規チャット
    // 起動のプレースホルダや短いチャットなど）は、アンカリングのガタつきが
    // 発生しないため paint 前にそのまま表示する。opacity:0 のベールを描画しない
    // ことで「一覧が一瞬消えてまた表示される」挙動を避ける。
    // If the content fits the viewport (short chat or launch placeholder), no scroll
    // correction will happen — reveal without the opacity veil to avoid a flash.
    const listElement = chatMessagesRef.current;
    const needsBottomAnchoring =
      !!listElement && listElement.scrollHeight - listElement.clientHeight > 1;
    if (!needsBottomAnchoring || typeof window === "undefined") {
      setIsInitialContentRevealed(true);
      return;
    }

    const animationFrameIds: number[] = [];

    // 動的行高の計測が数フレームにまたがるため、末尾アンカリングを 3 連続フレームで
    // 再調整し、計測が落ち着いた次フレームでフェードイン表示する。wall-clock の
    // setTimeout ではなく requestAnimationFrame に紐づけることで、遷移時の重い
    // 再レンダリング中でも復帰が遅れて「空白のまま」見えてしまうのを防ぐ。
    // Re-anchor over 3 consecutive rAF frames while row heights settle, then fade in.
    // rAF-chaining avoids the "blank gap" that setTimeout would cause during heavy renders.
    const revealAfterSettle = () => {
      scrollListToEnd();
      setIsInitialContentRevealed(true);
    };

    animationFrameIds.push(
      window.requestAnimationFrame(() => {
        scrollListToEnd();
        animationFrameIds.push(
          window.requestAnimationFrame(() => {
            scrollListToEnd();
            animationFrameIds.push(window.requestAnimationFrame(revealAfterSettle));
          }),
        );
      }),
    );

    return () => {
      animationFrameIds.forEach((frameId) => {
        window.cancelAnimationFrame(frameId);
      });
    };
  }, [chatMessagesRef, rows, scrollListToEnd]);

  // 思考中インジケーターが表示される間、複数フレームにまたがって末尾スクロールを維持する。
  // 80ms・220ms の setTimeout はリサイズ完了後のスクロール漏れを補完するフォールバック。
  // While the thinking indicator is visible, keep scrolling to the bottom across multiple
  // frames. The 80ms/220ms timeouts catch any scroll misses after layout completes.
  useIsomorphicLayoutEffect(() => {
    if (!shouldRevealThinking) return;

    scrollThinkingIntoView();

    if (typeof window === "undefined") return;

    const animationFrameIds: number[] = [];
    const timeoutIds: number[] = [];
    const scheduleAnimationFrame = () => {
      const frameId = window.requestAnimationFrame(() => {
        scrollThinkingIntoView();
      });
      animationFrameIds.push(frameId);
    };

    scheduleAnimationFrame();
    const nestedFrameId = window.requestAnimationFrame(() => {
      scrollThinkingIntoView();
      scheduleAnimationFrame();
    });
    animationFrameIds.push(nestedFrameId);

    [80, 220].forEach((delay) => {
      const timeoutId = window.setTimeout(scrollThinkingIntoView, delay);
      timeoutIds.push(timeoutId);
    });

    return () => {
      animationFrameIds.forEach((frameId) => {
        window.cancelAnimationFrame(frameId);
      });
      timeoutIds.forEach((timeoutId) => {
        window.clearTimeout(timeoutId);
      });
    };
  }, [scrollThinkingIntoView, shouldRevealThinking]);

  return (
    <List
      aria-busy={isChatLaunching || isGenerating ? "true" : undefined}
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="チャットメッセージ"
      className={`chat-messages chat-messages--virtual scroll-pb-24${
        isInitialContentRevealed ? "" : " chat-messages--anchoring"
      }`}
      defaultHeight={480}
      id="chat-messages"
      listRef={setListRef}
      onResize={handleListResize}
      overscanCount={6}
      role="log"
      rowComponent={ChatMessageRow}
      rowCount={rows.length}
      rowHeight={rowHeight}
      rowProps={rowProps}
      style={{ width: "100%" }}
    />
  );
}

// 不要な再レンダリングを防ぐため memo でラップしてエクスポートする。
// Wrap in memo to prevent re-renders when parent re-renders with unchanged props.
export const ChatMessageList = memo(ChatMessageListComponent);
ChatMessageList.displayName = "ChatMessageList";
