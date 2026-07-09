import { useRouter } from "next/router";
import { useState, useRef, useEffect, useCallback, useMemo, type FormEvent } from "react";

import {
  buildAiAgentHttpError,
  collectVisiblePageDom,
  createAiAgentMessageId,
  isAllowedNavigationPath,
  isSafeInternalPath,
  readSseStream,
  type ActionPlan,
  type ActionStep,
  type Message,
} from "../../lib/chat_page/ai_agent";
import {
  ACTION_LABELS,
  INITIAL_PROGRESS_MESSAGE,
  MAX_DOM_LENGTH,
  MAX_INPUT_LENGTH,
  MAX_SEND_MESSAGES,
  QUICK_PROMPTS,
  clearPendingActionSteps,
  clearStoredConversation,
  executeActionSteps,
  getInternalPathname,
  getMessageStorageKeys,
  isClientNavigableRoute,
  readPendingActionState,
  readStoredExecutedIds,
  readStoredMessages,
  waitForPendingResumeReady,
  waitForRouteSettled,
  writePendingActionSteps,
  type ExecutionProgress,
  type MiniChatProps,
  type NavigateInternal,
  type UnloadContext,
} from "../../lib/chat_page/mini_chat_runtime";
import { writeSessionJson } from "../../lib/utils";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import MarkdownContent from "../MarkdownContent";

// MiniChat — AI エージェントとの会話 UI コンポーネント
// MiniChat — embeddable chat panel that lets users interact with the AI agent
export function MiniChat({
  memoId = null,
  storageScope,
  quickPrompts = QUICK_PROMPTS,
  placeholderTitle = "操作支援エージェント",
  placeholderDescription = "画面の使い方、次の操作、入力内容の整理を短い会話で進められます。",
  inputPlaceholder = "この画面でやりたいことを相談する",
  enableActions = true,
  persistConversation = true,
}: MiniChatProps = {}) {
  const router = useRouter();
  // storageScope が変わったときだけキーを再計算する
  // Recompute storage keys only when storageScope changes to avoid unnecessary object churn
  const storageKeys = useMemo(() => getMessageStorageKeys(storageScope), [storageScope]);
  // memoId を数値に正規化する — 無効値は null にフォールバック
  // Normalizes memoId to a positive integer or null so the API always receives a clean value
  const numericMemoId = useMemo(() => {
    if (memoId === null || memoId === undefined || memoId === "") return null;
    const parsed = Number(memoId);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [memoId]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [executingMessageId, setExecutingMessageId] = useState<string | null>(null);
  const [executionProgress, setExecutionProgress] = useState<ExecutionProgress | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<string>>(new Set());
  // ハイドレーション完了フラグ — SSR とクライアント状態の不一致を防ぐ
  // Hydration flag prevents rendering stale server-side state before client storage is read
  const [hydrated, setHydrated] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // 非同期ハンドラが最新のメッセージを参照できるように ref で同期させる
  // Keeps a ref in sync so async callbacks always see the latest messages without stale closures
  const messagesRef = useRef<Message[]>([]);
  const unloadContextRef = useRef<UnloadContext>(null);
  const routerRef = useRef(router);
  const trimmedInput = input.trim();

  // Keep router ref current so the stable navigateInternal callback always pushes via the
  // latest router instance.
  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  // Safety net: if an undetected click (e.g. a plain link or form submit) tears the page
  // down mid-execution, persist the remaining steps so they resume after the reload.
  useEffect(() => {
    const onBeforeUnload = () => {
      const context = unloadContextRef.current;
      if (context && context.remaining.length) {
        writePendingActionSteps(context.remaining, context.expectedPath);
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // クライアントサイドを優先し、失敗した場合はフルロードにフォールバックする
  // Prefers client-side navigation for smooth UX and falls back to hard navigation when needed
  const navigateInternal = useCallback<NavigateInternal>(async (path) => {
    if (!isSafeInternalPath(path) || !isAllowedNavigationPath(path)) {
      return { ok: false, message: "この遷移は許可されていません。", clientSide: false, needsReplan: false };
    }
    const targetPathname = getInternalPathname(path);
    if (targetPathname && isClientNavigableRoute(targetPathname)) {
      try {
        await routerRef.current.push(path);
        const settled = await waitForRouteSettled(path);
        return { ok: settled.ok, message: settled.message, clientSide: true, needsReplan: settled.needsReplan };
      } catch {
        // Client navigation failed; fall back to a full document load below.
      }
    }
    window.location.href = path;
    return { ok: true, clientSide: false };
  }, []);

  const setUnloadContext = useCallback((context: UnloadContext) => {
    unloadContextRef.current = context;
  }, []);
  const currentProgressText = statusText ?? progressSteps[progressSteps.length - 1] ?? null;

  // Keep ref in sync for stale-closure-safe access in async handlers
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // 重複する進捗メッセージを除去してステップリストに追加する
  // Appends a progress step, skipping it if it's identical to the last entry to avoid duplicates
  const appendProgressStep = (message: string) => {
    setStatusText(message);
    setProgressSteps((prev) => (
      prev[prev.length - 1] === message ? prev : [...prev, message]
    ));
  };

  // AI エージェント API を呼び出し、SSE ストリームから最終応答を構築する
  // Calls the AI agent API and parses the SSE stream to build the assistant message
  const requestAiAgentMessage = async (
    nextMessages: Message[],
    signal: AbortSignal,
  ): Promise<Message> => {
    const response = await resilientFetch(
      "/api/ai-agent",
      {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          // 直近 MAX_SEND_MESSAGES 件に絞ってペイロードサイズを制限する
          // Limits history to MAX_SEND_MESSAGES to keep the API payload manageable
          messages: nextMessages.slice(-MAX_SEND_MESSAGES).map((m) => ({ role: m.sender, content: m.text })),
          current_page: typeof window !== "undefined" ? window.location.pathname : null,
          current_dom: enableActions ? collectVisiblePageDom().slice(0, MAX_DOM_LENGTH) : "",
          ...(numericMemoId ? { memo_id: numericMemoId } : {}),
        }),
      },
      { timeoutMs: 0 }
    );

    if (!response.ok) {
      throw await buildAiAgentHttpError(response);
    }

    let assistantText = "応答を取得できませんでした。もう一度試してください。";
    let actionPlan: ActionPlan | undefined;
    let isError = false;

    // SSE イベントを逐次処理してプログレスと最終応答を分離する
    // Processes SSE events incrementally, separating progress updates from the final response
    for await (const event of readSseStream(response)) {
      if (event.type === "progress") {
        appendProgressStep(event.message);
      } else if (event.type === "done") {
        assistantText = event.response.trim() || assistantText;
        break;
      } else if (event.type === "action_plan") {
        assistantText = event.description;
        actionPlan = enableActions ? { description: event.description, steps: event.steps } : undefined;
        break;
      } else if (event.type === "error") {
        assistantText = event.message;
        isError = true;
        break;
      }
    }

    return { id: createAiAgentMessageId(), sender: "assistant", text: assistantText, actionPlan, isError };
  };

  // ユーザーのメッセージを送信し、AI 応答を受け取ってチャットに追加する
  // Sends the user's input to the AI agent and appends the response to the conversation
  const handleSend = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!trimmedInput || isGenerating) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userMessage: Message = { id: createAiAgentMessageId(), sender: "user", text: trimmedInput };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setIsGenerating(true);
    setStatusText(INITIAL_PROGRESS_MESSAGE);
    setProgressSteps([INITIAL_PROGRESS_MESSAGE]);

    try {
      const assistantMessage = await requestAiAgentMessage(nextMessages, controller.signal);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      // AbortError はユーザーが意図的に停止したため静かに無視する
      // AbortError is intentional (user clicked stop), so suppress it silently
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessages((prev) => [
        ...prev,
        {
          id: createAiAgentMessageId(),
          sender: "assistant",
          text: error instanceof Error ? error.message : "AIエージェントの応答生成に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  // 進行中の AI 応答を中断する
  // Aborts the in-flight API request so generation stops immediately
  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  // エラーメッセージを除いて直前の会話状態に戻し、再送信する
  // Removes the error message and retries the request from the last valid conversation state
  const handleRetry = async (errorMsgIndex: number) => {
    const messagesBeforeError = messages.slice(0, errorMsgIndex);
    setMessages(messagesBeforeError);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsGenerating(true);
    setStatusText(INITIAL_PROGRESS_MESSAGE);
    setProgressSteps([INITIAL_PROGRESS_MESSAGE]);

    try {
      const assistantMessage = await requestAiAgentMessage(messagesBeforeError, controller.signal);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessages((prev) => [
        ...prev,
        {
          id: createAiAgentMessageId(),
          sender: "assistant",
          text: error instanceof Error ? error.message : "AIエージェントの応答生成に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  // テキストをクリップボードにコピーし、2 秒後にアイコンを元に戻す
  // Copies text to the clipboard and resets the copied state after 2 seconds
  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex((prev) => (prev === index ? null : prev)), 2000);
    } catch {
      // clipboard API unavailable
    }
  };

  // Re-observe the current page and ask the model for a fresh, executable plan. Used both
  // when a step fails mid-flight and when post-navigation targets can't be found.
  const replanAfterFailure = async (failureText: string, failedStepIndex?: number) => {
    const failedStepText = typeof failedStepIndex === "number"
      ? `失敗ステップ: ${failedStepIndex + 1}`
      : "";
    // 最新の DOM 状態を含む再計画プロンプトを構築する
    // Builds a replan prompt that includes the failure reason so the model can adapt its plan
    const replanPrompt = [
      "前回の操作計画は実行中に失敗しました。",
      failedStepText,
      `失敗理由: ${failureText}`,
      "現在の画面DOMを再観測し、成功確認しやすい型付きアクションAPIを優先して、実行可能な操作計画だけを作り直してください。",
    ].filter(Boolean).join("\n");

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsGenerating(true);
    setStatusText("画面を再確認しています...");
    setProgressSteps(["画面を再確認しています..."]);

    try {
      const replanMessage = await requestAiAgentMessage(
        [
          ...messagesRef.current,
          { id: createAiAgentMessageId(), sender: "user", text: replanPrompt },
        ],
        controller.signal,
      );
      setMessages((prev) => [
        ...prev,
        {
          id: createAiAgentMessageId(),
          sender: "assistant",
          text: `操作を途中で停止しました。${failureText}`,
        },
        replanMessage,
      ]);
    } catch (replanError) {
      if (!(replanError instanceof DOMException && replanError.name === "AbortError")) {
        setMessages((prev) => [
          ...prev,
          {
            id: createAiAgentMessageId(),
            sender: "assistant",
            text: replanError instanceof Error ? replanError.message : "操作の再計画に失敗しました。",
            isError: true,
          },
        ]);
      }
    } finally {
      abortControllerRef.current = null;
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  // アクション計画を実行し、進捗状態を更新し、失敗時は再計画を試みる
  // Runs an action plan, tracks per-step progress, and triggers replanning on failure
  const handleExecuteActions = async (steps: ActionStep[], messageId: string) => {
    setExecutingMessageId(messageId);
    setExecutionProgress({
      messageId,
      currentStepIndex: null,
      completedStepIndexes: [],
    });
    try {
      const result = await executeActionSteps(steps, {
        navigateInternal,
        setUnloadContext,
        // ステップの current/complete 遷移ごとに UI の進捗表示を更新する
        // Updates the step-level progress indicator as each step transitions to current or complete
        onStepProgress: (stepIndex, status) => {
          setExecutionProgress((current) => {
            if (!current || current.messageId !== messageId) {
              return {
                messageId,
                currentStepIndex: status === "current" ? stepIndex : null,
                completedStepIndexes: status === "complete" ? [stepIndex] : [],
              };
            }
            const completed = new Set(current.completedStepIndexes);
            if (status === "complete") completed.add(stepIndex);
            return {
              messageId,
              currentStepIndex: status === "current"
                ? stepIndex
                : current.currentStepIndex === stepIndex
                  ? null
                  : current.currentStepIndex,
              completedStepIndexes: Array.from(completed).sort((a, b) => a - b),
            };
          });
        },
      });
      if (result.ok) {
        setExecutedSet((prev) => new Set([...prev, messageId]));
        // ページ遷移が発生した場合は実行済み ID をストレージに先行保存する
        // Eagerly persists the executed ID when navigation is pending so it survives the reload
        if (persistConversation && result.pendingNavigation) {
          const merged = Array.from(new Set([...readStoredExecutedIds(messagesRef.current, storageKeys), messageId]));
          writeSessionJson(storageKeys.executed, merged);
        }
      } else if (result.needsReplan === false) {
        // A terminal, self-explanatory stop (e.g. login required): just inform the user.
        setMessages((prev) => [
          ...prev,
          {
            id: createAiAgentMessageId(),
            sender: "assistant",
            text: result.message || "操作を完了できませんでした。",
            isError: true,
          },
        ]);
      } else {
        await replanAfterFailure(result.message || "画面状態を確認できませんでした。", result.failedStepIndex);
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: createAiAgentMessageId(),
          sender: "assistant",
          text: error instanceof Error ? error.message : "操作の実行に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      setUnloadContext(null);
      setExecutingMessageId(null);
      setExecutionProgress(null);
    }
  };

  // 初回マウント時にセッションストレージから会話・実行済みセット・未完了ステップを復元する
  // On mount, restores conversation history and resumes any cross-reload pending action steps
  useEffect(() => {
    if (!persistConversation) {
      clearStoredConversation(storageKeys);
      setMessages([]);
      setExecutedSet(new Set());
      setHydrated(true);
      return undefined;
    }

    const storedMessages = readStoredMessages(storageKeys);
    const storedExecuted = readStoredExecutedIds(storedMessages, storageKeys);
    if (storedMessages.length) setMessages(storedMessages);
    if (storedExecuted.length) setExecutedSet(new Set(storedExecuted));
    setHydrated(true);

    if (!enableActions) return undefined;

    const pendingActionState = readPendingActionState();
    const pendingSteps = pendingActionState.steps;
    if (!pendingSteps.length) return undefined;

    let timer: number | undefined;
    setMessages((prev) => {
      const pendingMessageId = createAiAgentMessageId();
      // ページ準備完了を確認してから再開実行を開始する
      // Defers execution until waitForPendingResumeReady confirms the page is ready
      timer = window.setTimeout(async () => {
        const ready = await waitForPendingResumeReady(pendingActionState);
        if (!ready.ok) {
          clearPendingActionSteps();
          if (ready.needsReplan) {
            // The destination loaded but the blind-planned targets aren't there: re-observe.
            void replanAfterFailure(ready.message || "移動後のページ準備を確認できませんでした。");
          } else {
            setMessages((current) => [
              ...current,
              {
                id: createAiAgentMessageId(),
                sender: "assistant",
                text: ready.message || "移動後のページ準備を確認できませんでした。",
                isError: true,
              },
            ]);
          }
          return;
        }
        void handleExecuteActions(pendingSteps, pendingMessageId);
      }, 360);
      return [
        ...prev,
        {
          id: pendingMessageId,
          sender: "assistant",
          text: "移動後の残り操作を続けます。",
          actionPlan: {
            description: "移動後の残り操作を続けます。",
            steps: pendingSteps,
          },
        },
      ];
    });

    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [enableActions, persistConversation, storageKeys]);

  // メッセージが変わるたびにセッションストレージを更新して会話を永続化する
  // Syncs messages to sessionStorage on every change so the conversation survives page reloads
  useEffect(() => {
    if (!hydrated || !persistConversation) return;
    writeSessionJson(
      storageKeys.messages,
      messages.map(({ id, sender, text, actionPlan, isError }) => ({ id, sender, text, actionPlan, isError })),
    );
    writeSessionJson(storageKeys.timestamp, messages.length > 0 ? Date.now() : 0);
  }, [hydrated, messages, persistConversation, storageKeys]);

  // 実行済みセットが変わるたびにストレージを更新する
  // Persists executed message IDs whenever the set changes so they survive reloads
  useEffect(() => {
    if (!hydrated || !persistConversation) return;
    writeSessionJson(storageKeys.executed, Array.from(executedSet));
  }, [hydrated, executedSet, persistConversation, storageKeys]);

  // 新しいメッセージや進捗テキストが追加されたら最下部にスクロールする
  // Scrolls the message list to the bottom whenever content changes so the latest reply is visible
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isGenerating, statusText, progressSteps.length]);

  return (
    <div className="mini-chat-container">
      <div className="mini-chat-messages" ref={scrollRef}>
        {/* メッセージがない場合はプレースホルダーと候補プロンプトを表示する */}
        {/* Show placeholder content and quick prompt suggestions when the conversation is empty */}
        {messages.length === 0 && (
          <div className="mini-chat-placeholder">
            <span className="mini-chat-robot-icon" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <strong>{placeholderTitle}</strong>
            <p>{placeholderDescription}</p>
            <div className="mini-chat-suggestions" aria-label="入力候補">
              {quickPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="mini-chat-suggestion"
                  onClick={() => setInput(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
        {/* 各メッセージをアバターとコンテンツエリアで描画する */}
        {/* Renders each message with its avatar and content area, using sender-specific styles */}
        {messages.map((msg, i) => (
          <div key={msg.id} className={`mini-chat-message mini-chat-message--${msg.sender}`}>
            <span className="mini-chat-avatar" aria-hidden="true">
              <i className={`bi ${msg.sender === "user" ? "bi-person" : "bi-stars"}`}></i>
            </span>
            <div className={`mini-chat-text-wrapper${msg.isError ? " mini-chat-text-wrapper--error" : ""}`}>
              {msg.sender === "assistant" ? (
                <MarkdownContent text={msg.text} className="mini-chat-text mini-chat-markdown" />
              ) : (
                <div className="mini-chat-text">{msg.text}</div>
              )}
              {/* アクション計画が含まれている場合、ステップ一覧と実行ボタンを表示する */}
              {/* Renders the action plan step list and execute button when an action plan is attached */}
              {enableActions && msg.actionPlan && (
                <div className="mini-chat-action-plan">
                  <ol className="mini-chat-action-steps">
                    {msg.actionPlan.steps.map((step, si) => (
                      <li
                        key={si}
                        className={`mini-chat-action-step ${
                          executionProgress?.messageId === msg.id && executionProgress.currentStepIndex === si
                            ? "is-current"
                            : executionProgress?.messageId === msg.id && executionProgress.completedStepIndexes.includes(si)
                              ? "is-complete"
                              : executedSet.has(msg.id)
                                ? "is-complete"
                                : ""
                        }`.trim()}
                        aria-current={
                          executionProgress?.messageId === msg.id && executionProgress.currentStepIndex === si
                            ? "step"
                            : undefined
                        }
                      >
                        <span className={`mini-chat-action-badge mini-chat-action-badge--${step.action}`}>
                          {ACTION_LABELS[step.action]}
                        </span>
                        <span className="mini-chat-action-index">{si + 1}</span>
                        {step.description}
                      </li>
                    ))}
                  </ol>
                  <button
                    type="button"
                    className="mini-chat-execute-btn"
                    onClick={() => handleExecuteActions(msg.actionPlan!.steps, msg.id)}
                    disabled={executingMessageId === msg.id || executedSet.has(msg.id)}
                    aria-label="操作を実行"
                  >
                    {executingMessageId === msg.id ? (
                      <><i className="bi bi-three-dots"></i> 実行中...</>
                    ) : executedSet.has(msg.id) ? (
                      <><i className="bi bi-check2"></i> 実行済み</>
                    ) : (
                      <><i className="bi bi-play-fill"></i> 実行</>
                    )}
                  </button>
                </div>
              )}
              {/* アシスタントのメッセージにはコピーボタンとエラー時の再試行ボタンを表示する */}
              {/* Shows copy and (on error) retry actions beneath each assistant message */}
              {msg.sender === "assistant" && (
                <div className="mini-chat-message-toolbar">
                  <button
                    type="button"
                    className="mini-chat-copy-btn"
                    onClick={() => void handleCopy(msg.text, i)}
                    aria-label="回答をコピー"
                  >
                    <i className={`bi ${copiedIndex === i ? "bi-check2" : "bi-copy"}`}></i>
                    {copiedIndex === i ? "コピー済み" : "コピー"}
                  </button>
                  {msg.isError && (
                    <button
                      type="button"
                      className="mini-chat-retry-btn"
                      onClick={() => void handleRetry(i)}
                      disabled={isGenerating}
                      aria-label="再試行"
                    >
                      <i className="bi bi-arrow-clockwise"></i>
                      再試行
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {/* 生成中はタイピングインジケーターまたは SSE 進捗ステップを表示する */}
        {/* Shows a typing indicator or SSE progress list while the AI response is streaming */}
        {isGenerating ? (
          <div className="mini-chat-message mini-chat-message--assistant mini-chat-message--typing" aria-live="polite">
            <span className="mini-chat-avatar" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <div className="mini-chat-text-wrapper">
              {currentProgressText ? (
                <div className="mini-chat-progress" role="status">
                  <span className="mini-chat-status-text">{currentProgressText}</span>
                  {progressSteps.length > 0 ? (
                    <ol className="mini-chat-progress-list" aria-label="AIエージェントの進捗">
                      {progressSteps.map((step, stepIndex) => (
                        <li
                          key={`${step}-${stepIndex}`}
                          className={`mini-chat-progress-step ${
                            stepIndex === progressSteps.length - 1 ? "is-current" : "is-complete"
                          }`}
                        >
                          {step}
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </div>
              ) : (
                <>
                  <span className="mini-chat-typing-dot"></span>
                  <span className="mini-chat-typing-dot"></span>
                  <span className="mini-chat-typing-dot"></span>
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <form className="mini-chat-input-area" onSubmit={handleSend}>
        <div className="mini-chat-input-wrapper">
          <input
            type="text"
            className="mini-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={inputPlaceholder}
            aria-label="AIサポートへのメッセージ"
            maxLength={MAX_INPUT_LENGTH}
            disabled={isGenerating}
          />
          {/* 生成中は停止ボタン、それ以外は送信ボタンを表示する */}
          {/* Toggles between stop and send buttons based on whether generation is in progress */}
          {isGenerating ? (
            <button
              type="button"
              className="mini-chat-stop-btn"
              onClick={handleStop}
              aria-label="生成を停止"
            >
              <i className="bi bi-stop-fill"></i>
            </button>
          ) : (
            <button
              type="submit"
              className="mini-chat-send-btn"
              disabled={!trimmedInput}
              aria-label="送信"
            >
              <i className="bi bi-arrow-up-short"></i>
            </button>
          )}
        </div>
        {/* 会話履歴をクリアするボタン — メッセージがないか生成中は無効化 */}
        {/* Clears the conversation history; disabled while generating or when there's nothing to clear */}
        <button
          type="button"
          className="mini-chat-action-btn"
          onClick={() => {
            setMessages([]);
            setExecutedSet(new Set());
          }}
          disabled={!messages.length || isGenerating}
          aria-label="会話をクリア"
        >
          <i className="bi bi-arrow-counterclockwise"></i>
        </button>
      </form>
    </div>
  );
}
