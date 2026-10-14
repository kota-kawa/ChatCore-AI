import { fireEvent, render } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ChatMainSection } from "../components/chat_page/chat_main_section";
import { HomePageContextProvider } from "../contexts/chat_page/home_page_context";
import type { useHomePageController } from "../hooks/chat_page/use_home_page_controller";

type ControllerState = ReturnType<typeof useHomePageController>;

vi.mock("../components/chat_page/chat_message_list", () => ({
  ChatMessageList: ({ setupInfo }: { setupInfo?: string }) => <span data-testid="setup-preview">{setupInfo ?? "なし"}</span>,
}));
vi.mock("../components/chat_page/chat_room_card", () => ({ ChatRoomCard: () => null }));
vi.mock("../components/chat_page/chat_room_search", () => ({ ChatRoomSearch: () => null }));
vi.mock("../components/ui/inline_loading", () => ({ InlineLoading: () => null }));
vi.mock("../components/ui/skeleton", () => ({ Skeleton: () => null }));
vi.mock("../components/chat_page/setup_attach_menu", () => ({
  KnowledgeLookupChips: () => null,
  SetupAttachMenu: () => null,
}));
vi.mock("../hooks/chat_page/use_chat_attachment_dropzone", () => ({
  useChatAttachmentDropzone: () => ({
    attachSelectedFiles: vi.fn(),
    isAttachmentDropActive: false,
    attachmentDropzoneProps: {},
  }),
}));
vi.mock("../hooks/chat_page/use_chat_tool_approvals", () => ({
  useChatToolApprovals: () => ({ handleToolApprovalDecide: vi.fn(async () => undefined) }),
}));
vi.mock("../contexts/locale_context", () => ({
  useTranslation: () => ({ locale: "ja", t: (key: string) => key }),
}));

function ChatInputHarness() {
  const [chatInput, setChatInput] = useState("");
  const [setupInfo, setSetupInfo] = useState("");
  const [pageViewState, setPageViewState] = useState<"chat" | "launching">("chat");
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const controller = {
    loggedIn: true,
    pageViewState,
    isChatVisible: true,
    isSetupVisible: pageViewState !== "chat",
    isChatLaunching: pageViewState === "launching",
    setupInfo,
    personalKnowledgeEnabled: false,
    sharedPromptsEnabled: false,
    selectedModel: "gpt-oss-120b",
    selectedModelShortLabel: "Model",
    chatHeaderModelMenuOpen: false,
    chatHeaderModelSelectRef: { current: null },
    setPersonalKnowledgeEnabled: () => undefined,
    setSharedPromptsEnabled: () => undefined,
    setSelectedModel: () => undefined,
    setChatHeaderModelMenuOpen: () => undefined,
    showSetupForm: () => undefined,
    tasks: [],
    launchingTaskId: null,
    launchingTaskName: null,
    projects: [],
    openProject: () => undefined,
    openNewProjectModal: () => undefined,
    hasCurrentRoom: true,
    sidebarOpen: false,
    chatRooms: [],
    chatRoomsHasMore: false,
    isChatRoomsInitialLoading: false,
    isLoadingMoreChatRooms: false,
    currentRoomId: "room-1",
    currentRoomMode: "normal",
    openRoomActionsFor: null,
    isRoomSelectionMode: false,
    selectedRoomIds: new Set<string>(),
    isBulkDeletingRooms: false,
    chatMessageListResetKey: 0,
    historyHasMore: false,
    historyNextBeforeId: null,
    isLoadingOlder: false,
    messages: [],
    chatMessagesRef,
    chatInput,
    isGenerating: false,
    openShareModal: () => undefined,
    handleNewChat: () => undefined,
    handleBulkDeleteRooms: async () => undefined,
    cancelRoomSelection: () => undefined,
    setSidebarOpen: () => undefined,
    loadMoreChatRooms: async () => undefined,
    loadOlderChatHistory: async () => undefined,
    setChatInput,
    attachedFiles: [],
    setAttachedFiles: () => undefined,
    handleChatInputKeyDown: () => undefined,
    handleSendMessage: () => setChatInput(""),
    handleRegenerateMessage: () => undefined,
    handleEditAndRegenerateMessage: () => undefined,
    handleSwitchBranch: () => undefined,
    applyToolApproval: async () => undefined,
    temporaryModeEnabled: false,
    storedSetupStateLoaded: true,
    selectedModelLabel: "Model",
    modelMenuOpen: false,
    modelSelectRef: { current: null },
    setSetupInfo,
    setTemporaryModeEnabled: () => undefined,
    setModelMenuOpen: () => undefined,
    closeNewPromptModal: () => undefined,
    openNewPromptModal: () => undefined,
    isTaskOrderEditing: false,
    isNewPromptModalOpen: false,
    tasksExpanded: false,
    taskCollapseLimit: 3,
    showTaskToggleButton: false,
    visibleTaskCountText: "",
    draggingTaskIndex: null,
    toggleTaskOrderEditing: () => undefined,
    handleTaskDragStart: () => undefined,
    handleTaskDragEnd: () => undefined,
    handleTaskCardLaunch: async () => undefined,
    handleTaskDelete: async () => undefined,
    openTaskEditModal: () => undefined,
    setTaskDetail: () => undefined,
    setTasksExpanded: () => undefined,
    isAiAgentModalOpen: false,
    openAiAgentModal: () => undefined,
    closeAiAgentModal: () => undefined,
    toggleAiAgentModal: () => undefined,
    handleAccessChat: async () => undefined,
    switchChatRoom: async () => undefined,
    handleSetupSendMessage: async () => undefined,
    setOpenRoomActionsFor: () => undefined,
    handleRenameRoom: async () => undefined,
    handleToggleRoomPin: async () => undefined,
    handleDeleteRoom: async () => undefined,
    enterRoomSelectionMode: () => undefined,
    toggleRoomSelection: () => undefined,
    loadProjects: async () => undefined,
    closeProject: () => undefined,
    refreshProjectDetail: async () => undefined,
    closeNewProjectModal: () => undefined,
    createProject: async () => undefined,
    updateProject: async () => undefined,
    deleteProject: async () => undefined,
    assignRoomToProject: async () => undefined,
    setNewChatProject: () => undefined,
  } as unknown as ControllerState;

  return (
    <HomePageContextProvider controller={controller}>
      <button
        type="button"
        id="start-launch"
        onClick={() => {
          setSetupInfo("起動時の環境");
          setPageViewState("launching");
        }}
      >
        start launch
      </button>
      <button type="button" id="update-launch-preview" onClick={() => setSetupInfo("更新した環境")}>
        update preview
      </button>
      <ChatMainSection />
    </HomePageContextProvider>
  );
}

describe("chat input height measurement", () => {
  it("measures once per input change, caps at six lines, and shrinks after send reset", () => {
    const { container } = render(<ChatInputHarness />);
    const textarea = container.querySelector<HTMLTextAreaElement>("#user-input");
    expect(textarea).not.toBeNull();
    if (!textarea) throw new Error("Chat input did not render.");
    const getComputedStyle = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      lineHeight: "20px",
      paddingTop: "4px",
      paddingBottom: "4px",
      borderTopWidth: "1px",
      borderBottomWidth: "1px",
    } as CSSStyleDeclaration);
    let scrollHeightReads = 0;
    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      get: () => {
        scrollHeightReads += 1;
        if (textarea.value === "") return 26;
        return textarea.value.split("\n").length > 6 ? 200 : 54;
      },
    });

    const maxHeight = 20 * 6 + 4 + 4 + 1 + 1;

    getComputedStyle.mockClear();
    fireEvent.change(textarea, { target: { value: "一行目\n二行目\n三行目" } });

    expect(textarea.value).toBe("一行目\n二行目\n三行目");
    expect(getComputedStyle).toHaveBeenCalledTimes(1);
    expect(scrollHeightReads).toBe(1);
    expect(textarea.style.height).toBe("54px");
    expect(textarea.style.overflowY).toBe("hidden");

    getComputedStyle.mockClear();
    scrollHeightReads = 0;
    fireEvent.change(textarea, { target: { value: "1\n2\n3\n4\n5\n6\n7" } });

    expect(getComputedStyle).toHaveBeenCalledTimes(1);
    expect(scrollHeightReads).toBe(1);
    expect(textarea.style.height).toBe(`${maxHeight}px`);
    expect(textarea.style.overflowY).toBe("auto");

    getComputedStyle.mockClear();
    scrollHeightReads = 0;
    const sendButton = container.querySelector<HTMLButtonElement>("#send-btn");
    expect(sendButton).not.toBeNull();
    if (!sendButton) throw new Error("Send button did not render.");
    fireEvent.click(sendButton);

    expect(textarea.value).toBe("");
    expect(getComputedStyle).toHaveBeenCalledTimes(1);
    expect(scrollHeightReads).toBe(1);
    expect(textarea.style.height).toBe("26px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  it("passes the latest setup text to the message list during the launch preview", () => {
    const { container } = render(<ChatInputHarness />);

    expect(container.querySelector("[data-testid='setup-preview']")).toHaveTextContent("なし");
    fireEvent.click(container.querySelector("#start-launch")!);
    expect(container.querySelector("[data-testid='setup-preview']")).toHaveTextContent("起動時の環境");

    fireEvent.click(container.querySelector("#update-launch-preview")!);
    expect(container.querySelector("[data-testid='setup-preview']")).toHaveTextContent("更新した環境");
  });
});
