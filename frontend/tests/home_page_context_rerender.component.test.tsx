import { act, fireEvent, render, screen } from "@testing-library/react";
import { memo, startTransition, Suspense, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  HomePageContextProvider,
  useHomePageChatContext,
  useHomePageChatUiContext,
  useHomePageLaunchPreviewContext,
  useHomePageProjectContext,
  useHomePageSetupChatContext,
  useHomePageTaskContext,
  useHomePageUiContext,
} from "../contexts/chat_page/home_page_context";
import type { useHomePageController } from "../hooks/chat_page/use_home_page_controller";
import type { NormalizedTask } from "../lib/chat_page/types";

type ControllerState = ReturnType<typeof useHomePageController>;

const chatMainRender = vi.fn();
const launchPreviewRender = vi.fn();
const noop = () => undefined;
const modelSelectRef = { current: null };
const chatHeaderModelSelectRef = { current: null };
let latestTaskLaunch = vi.fn(async (_task: NormalizedTask) => undefined);
let latestSetupSend = vi.fn(async () => undefined);
const task = {
  task_id: 1,
  name: "要約",
  prompt_template: "要約してください",
  response_rules: "",
  output_skeleton: "",
  input_examples: "",
  output_examples: "",
  is_default: false,
} satisfies NormalizedTask;

function makeController(overrides: Partial<ControllerState> = {}): ControllerState {
  return {
    loggedIn: true,
    pageViewState: "setup",
    isChatVisible: false,
    isSetupVisible: true,
    isChatLaunching: false,
    setupInfo: "最初の入力",
    temporaryModeEnabled: false,
    personalKnowledgeEnabled: false,
    sharedPromptsEnabled: false,
    storedSetupStateLoaded: true,
    selectedModel: "model",
    modelMenuOpen: false,
    selectedModelLabel: "Model",
    selectedModelShortLabel: "M",
    modelSelectRef,
    chatHeaderModelMenuOpen: false,
    chatHeaderModelSelectRef,
    setSetupInfo: noop,
    setTemporaryModeEnabled: noop,
    setPersonalKnowledgeEnabled: noop,
    setSharedPromptsEnabled: noop,
    setSelectedModel: noop,
    setModelMenuOpen: noop,
    setChatHeaderModelMenuOpen: noop,
    showSetupForm: noop,
    tasks: [],
    handleTaskCardLaunch: noop,
    handleSetupSendMessage: async () => undefined,
    chatRooms: [],
    switchChatRoom: noop,
    handleAccessChat: noop,
    attachedFiles: [],
    setAttachedFiles: noop,
    projects: [],
    ...overrides,
  } as unknown as ControllerState;
}

function LaunchPreviewProbe() {
  const setupInfo = useHomePageLaunchPreviewContext();
  launchPreviewRender();
  return <span data-testid="launch-preview">{setupInfo ?? "なし"}</span>;
}

const ChatMainProbe = memo(function ChatMainProbe() {
  const ui = useHomePageChatUiContext();
  const tasks = useHomePageTaskContext();
  const chat = useHomePageChatContext();
  const projects = useHomePageProjectContext();
  chatMainRender();

  return (
    <section data-view={ui.pageViewState} data-task-count={tasks.tasks.length} data-chat-input={chat.chatInput}>
      <span data-testid="project-count">{projects.projects.length}</span>
      <LaunchPreviewProbe />
    </section>
  );
});

function SetupProbe() {
  const { setupInfo } = useHomePageUiContext();
  const { handleTaskCardLaunch } = useHomePageTaskContext();
  const { handleSetupSendMessage } = useHomePageSetupChatContext();

  return (
    <div>
      <span data-testid="setup-info">{setupInfo}</span>
      <button type="button" onClick={() => void handleTaskCardLaunch(task)}>launch-task</button>
      <button type="button" onClick={() => void handleSetupSendMessage()}>send-setup</button>
    </div>
  );
}

function Harness() {
  const [controller, setController] = useState(() => makeController());

  const updateSetupInfo = (setupInfo: string) => {
    latestTaskLaunch = vi.fn(async (_task: NormalizedTask) => undefined);
    latestSetupSend = vi.fn(async () => undefined);
    setController((previous) => makeController({
      ...previous,
      setupInfo,
      handleTaskCardLaunch: latestTaskLaunch,
      handleSetupSendMessage: latestSetupSend,
    }));
  };

  return (
    <>
      <button type="button" onClick={() => updateSetupInfo("編集中")}>update-setup</button>
      <button
        type="button"
        onClick={() => setController((previous) => makeController({
          ...previous,
          pageViewState: "launching",
          isChatVisible: true,
          isSetupVisible: true,
          isChatLaunching: true,
        }))}
      >
        start-launch
      </button>
      <button type="button" onClick={() => updateSetupInfo("最新の入力")}>update-launch-preview</button>
      <HomePageContextProvider controller={controller}>
        <ChatMainProbe />
        <SetupProbe />
      </HomePageContextProvider>
    </>
  );
}

describe("ホームページ Context の更新境界 / home page context update boundaries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    latestTaskLaunch = vi.fn(async (_task: NormalizedTask) => undefined);
    latestSetupSend = vi.fn(async () => undefined);
  });

  it("setup 入力中は非表示チャットを更新せず、起動プレビューと操作には最新値を渡す", () => {
    render(<Harness />);

    expect(chatMainRender).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("setup-info")).toHaveTextContent("最初の入力");
    expect(screen.getByTestId("launch-preview")).toHaveTextContent("なし");

    fireEvent.click(screen.getByRole("button", { name: "update-setup" }));

    expect(chatMainRender).toHaveBeenCalledTimes(1);
    expect(launchPreviewRender).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("setup-info")).toHaveTextContent("編集中");

    fireEvent.click(screen.getByRole("button", { name: "launch-task" }));
    fireEvent.click(screen.getByRole("button", { name: "send-setup" }));
    expect(latestTaskLaunch).toHaveBeenCalledWith(task);
    expect(latestSetupSend).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "start-launch" }));
    expect(screen.getByTestId("launch-preview")).toHaveTextContent("編集中");
    const rendersAfterLaunch = chatMainRender.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "update-launch-preview" }));

    expect(chatMainRender).toHaveBeenCalledTimes(rendersAfterLaunch);
    expect(screen.getByTestId("launch-preview")).toHaveTextContent("最新の入力");
  });
});


it("keeps committed launch handlers while a new render is suspended", async () => {
  const committedTaskLaunch = vi.fn(async (_task: NormalizedTask) => undefined);
  const pendingTaskLaunch = vi.fn(async (_task: NormalizedTask) => undefined);
  const committedSetupSend = vi.fn(async () => undefined);
  const pendingSetupSend = vi.fn(async () => undefined);
  const pending = new Promise<void>(() => undefined);

  function SuspendDraft() {
    const { setupInfo } = useHomePageUiContext();
    if (setupInfo === "pending") throw pending;
    return null;
  }

  function ConcurrentHarness() {
    const [controller, setController] = useState(() => makeController({
      handleTaskCardLaunch: committedTaskLaunch,
      handleSetupSendMessage: committedSetupSend,
    }));
    return (
      <>
        <button type="button" onClick={() => startTransition(() => setController(previous => ({
          ...previous,
          setupInfo: "pending",
          handleTaskCardLaunch: pendingTaskLaunch,
          handleSetupSendMessage: pendingSetupSend,
        })))}>pending update</button>
        <Suspense fallback={<span>loading</span>}>
          <HomePageContextProvider controller={controller}>
            <SetupProbe />
            <SuspendDraft />
          </HomePageContextProvider>
        </Suspense>
      </>
    );
  }

  render(<ConcurrentHarness />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "pending update" }));
  });
  expect(screen.getByTestId("setup-info")).toHaveTextContent("最初の入力");
  fireEvent.click(screen.getByRole("button", { name: "launch-task" }));
  fireEvent.click(screen.getByRole("button", { name: "send-setup" }));
  expect(committedTaskLaunch).toHaveBeenCalledWith(task);
  expect(committedSetupSend).toHaveBeenCalledTimes(1);
  expect(pendingTaskLaunch).not.toHaveBeenCalled();
  expect(pendingSetupSend).not.toHaveBeenCalled();
});
