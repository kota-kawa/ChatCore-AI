import { createContext, useContext, useMemo, type Context, type ReactNode } from "react";

type HomePageControllerState =
  ReturnType<typeof import("../../hooks/chat_page/use_home_page_controller").useHomePageController>;

type HomePageUiContextValue = Pick<
  HomePageControllerState,
  | "loggedIn"
  | "pageViewState"
  | "isChatVisible"
  | "isSetupVisible"
  | "isChatLaunching"
  | "setupInfo"
  | "temporaryModeEnabled"
  | "storedSetupStateLoaded"
  | "selectedModel"
  | "modelMenuOpen"
  | "selectedModelLabel"
  | "selectedModelShortLabel"
  | "modelSelectRef"
  | "chatHeaderModelMenuOpen"
  | "chatHeaderModelSelectRef"
  | "setSetupInfo"
  | "setTemporaryModeEnabled"
  | "setSelectedModel"
  | "setModelMenuOpen"
  | "setChatHeaderModelMenuOpen"
  | "showSetupForm"
>;

type HomePageTaskContextValue = Pick<
  HomePageControllerState,
  | "tasks"
  | "isTaskOrderEditing"
  | "isNewPromptModalOpen"
  | "tasksExpanded"
  | "showTaskToggleButton"
  | "visibleTaskCountText"
  | "launchingTaskName"
  | "draggingTaskIndex"
  | "toggleTaskOrderEditing"
  | "closeNewPromptModal"
  | "openNewPromptModal"
  | "handleTaskDragStart"
  | "handleTaskDragEnd"
  | "handleTaskCardLaunch"
  | "handleTaskDelete"
  | "openTaskEditModal"
  | "setTaskDetail"
  | "setTasksExpanded"
  | "isAiAgentModalOpen"
  | "openAiAgentModal"
  | "closeAiAgentModal"
  | "toggleAiAgentModal"
>;

type HomePageChatContextValue = Pick<
  HomePageControllerState,
  | "handleAccessChat"
  | "handleSetupSendMessage"
  | "hasCurrentRoom"
  | "sidebarOpen"
  | "chatRooms"
  | "currentRoomId"
  | "currentRoomMode"
  | "openRoomActionsFor"
  | "historyHasMore"
  | "historyNextBeforeId"
  | "isLoadingOlder"
  | "messages"
  | "chatMessagesRef"
  | "chatInput"
  | "isGenerating"
  | "openShareModal"
  | "handleNewChat"
  | "switchChatRoom"
  | "setOpenRoomActionsFor"
  | "handleRenameRoom"
  | "handleDeleteRoom"
  | "setSidebarOpen"
  | "loadOlderChatHistory"
  | "setChatInput"
  | "handleChatInputKeyDown"
  | "handleSendMessage"
>;

const HomePageUiContext = createContext<HomePageUiContextValue | null>(null);
const HomePageTaskContext = createContext<HomePageTaskContextValue | null>(null);
const HomePageChatContext = createContext<HomePageChatContextValue | null>(null);

type HomePageContextProviderProps = {
  controller: HomePageControllerState;
  children: ReactNode;
};

export function HomePageContextProvider({ controller, children }: HomePageContextProviderProps) {
  const uiValue = useMemo<HomePageUiContextValue>(
    () => ({
      loggedIn: controller.loggedIn,
      pageViewState: controller.pageViewState,
      isChatVisible: controller.isChatVisible,
      isSetupVisible: controller.isSetupVisible,
      isChatLaunching: controller.isChatLaunching,
      setupInfo: controller.setupInfo,
      temporaryModeEnabled: controller.temporaryModeEnabled,
      storedSetupStateLoaded: controller.storedSetupStateLoaded,
      selectedModel: controller.selectedModel,
      modelMenuOpen: controller.modelMenuOpen,
      selectedModelLabel: controller.selectedModelLabel,
      selectedModelShortLabel: controller.selectedModelShortLabel,
      modelSelectRef: controller.modelSelectRef,
      chatHeaderModelMenuOpen: controller.chatHeaderModelMenuOpen,
      chatHeaderModelSelectRef: controller.chatHeaderModelSelectRef,
      setSetupInfo: controller.setSetupInfo,
      setTemporaryModeEnabled: controller.setTemporaryModeEnabled,
      setSelectedModel: controller.setSelectedModel,
      setModelMenuOpen: controller.setModelMenuOpen,
      setChatHeaderModelMenuOpen: controller.setChatHeaderModelMenuOpen,
      showSetupForm: controller.showSetupForm,
    }),
    [
      controller.loggedIn,
      controller.pageViewState,
      controller.isChatVisible,
      controller.isSetupVisible,
      controller.isChatLaunching,
      controller.setupInfo,
      controller.temporaryModeEnabled,
      controller.storedSetupStateLoaded,
      controller.selectedModel,
      controller.modelMenuOpen,
      controller.selectedModelLabel,
      controller.selectedModelShortLabel,
      controller.modelSelectRef,
      controller.chatHeaderModelMenuOpen,
      controller.chatHeaderModelSelectRef,
      controller.setSetupInfo,
      controller.setTemporaryModeEnabled,
      controller.setSelectedModel,
      controller.setModelMenuOpen,
      controller.setChatHeaderModelMenuOpen,
      controller.showSetupForm,
    ],
  );

  const taskValue = useMemo<HomePageTaskContextValue>(
    () => ({
      tasks: controller.tasks,
      isTaskOrderEditing: controller.isTaskOrderEditing,
      isNewPromptModalOpen: controller.isNewPromptModalOpen,
      tasksExpanded: controller.tasksExpanded,
      showTaskToggleButton: controller.showTaskToggleButton,
      visibleTaskCountText: controller.visibleTaskCountText,
      launchingTaskName: controller.launchingTaskName,
      draggingTaskIndex: controller.draggingTaskIndex,
      toggleTaskOrderEditing: controller.toggleTaskOrderEditing,
      closeNewPromptModal: controller.closeNewPromptModal,
      openNewPromptModal: controller.openNewPromptModal,
      handleTaskDragStart: controller.handleTaskDragStart,
      handleTaskDragEnd: controller.handleTaskDragEnd,
      handleTaskCardLaunch: controller.handleTaskCardLaunch,
      handleTaskDelete: controller.handleTaskDelete,
      openTaskEditModal: controller.openTaskEditModal,
      setTaskDetail: controller.setTaskDetail,
      setTasksExpanded: controller.setTasksExpanded,
      isAiAgentModalOpen: controller.isAiAgentModalOpen,
      openAiAgentModal: controller.openAiAgentModal,
      closeAiAgentModal: controller.closeAiAgentModal,
      toggleAiAgentModal: controller.toggleAiAgentModal,
    }),
    [
      controller.tasks,
      controller.isTaskOrderEditing,
      controller.isNewPromptModalOpen,
      controller.tasksExpanded,
      controller.showTaskToggleButton,
      controller.visibleTaskCountText,
      controller.launchingTaskName,
      controller.draggingTaskIndex,
      controller.toggleTaskOrderEditing,
      controller.closeNewPromptModal,
      controller.openNewPromptModal,
      controller.handleTaskDragStart,
      controller.handleTaskDragEnd,
      controller.handleTaskCardLaunch,
      controller.handleTaskDelete,
      controller.openTaskEditModal,
      controller.setTaskDetail,
      controller.setTasksExpanded,
      controller.isAiAgentModalOpen,
      controller.openAiAgentModal,
      controller.closeAiAgentModal,
      controller.toggleAiAgentModal,
    ],
  );

  const chatValue = useMemo<HomePageChatContextValue>(
    () => ({
      handleAccessChat: controller.handleAccessChat,
      handleSetupSendMessage: controller.handleSetupSendMessage,
      hasCurrentRoom: controller.hasCurrentRoom,
      sidebarOpen: controller.sidebarOpen,
      chatRooms: controller.chatRooms,
      currentRoomId: controller.currentRoomId,
      currentRoomMode: controller.currentRoomMode,
      openRoomActionsFor: controller.openRoomActionsFor,
      historyHasMore: controller.historyHasMore,
      historyNextBeforeId: controller.historyNextBeforeId,
      isLoadingOlder: controller.isLoadingOlder,
      messages: controller.messages,
      chatMessagesRef: controller.chatMessagesRef,
      chatInput: controller.chatInput,
      isGenerating: controller.isGenerating,
      openShareModal: controller.openShareModal,
      handleNewChat: controller.handleNewChat,
      switchChatRoom: controller.switchChatRoom,
      setOpenRoomActionsFor: controller.setOpenRoomActionsFor,
      handleRenameRoom: controller.handleRenameRoom,
      handleDeleteRoom: controller.handleDeleteRoom,
      setSidebarOpen: controller.setSidebarOpen,
      loadOlderChatHistory: controller.loadOlderChatHistory,
      setChatInput: controller.setChatInput,
      handleChatInputKeyDown: controller.handleChatInputKeyDown,
      handleSendMessage: controller.handleSendMessage,
    }),
    [
      controller.handleAccessChat,
      controller.handleSetupSendMessage,
      controller.hasCurrentRoom,
      controller.sidebarOpen,
      controller.chatRooms,
      controller.currentRoomId,
      controller.currentRoomMode,
      controller.openRoomActionsFor,
      controller.historyHasMore,
      controller.historyNextBeforeId,
      controller.isLoadingOlder,
      controller.messages,
      controller.chatMessagesRef,
      controller.chatInput,
      controller.isGenerating,
      controller.openShareModal,
      controller.handleNewChat,
      controller.switchChatRoom,
      controller.setOpenRoomActionsFor,
      controller.handleRenameRoom,
      controller.handleDeleteRoom,
      controller.setSidebarOpen,
      controller.loadOlderChatHistory,
      controller.setChatInput,
      controller.handleChatInputKeyDown,
      controller.handleSendMessage,
    ],
  );

  return (
    <HomePageUiContext.Provider value={uiValue}>
      <HomePageTaskContext.Provider value={taskValue}>
        <HomePageChatContext.Provider value={chatValue}>{children}</HomePageChatContext.Provider>
      </HomePageTaskContext.Provider>
    </HomePageUiContext.Provider>
  );
}

function useRequiredContext<T>(context: Context<T | null>, contextName: string): T {
  const value = useContext(context);
  if (!value) {
    throw new Error(`${contextName} must be used within HomePageContextProvider.`);
  }
  return value;
}

export function useHomePageUiContext() {
  return useRequiredContext(HomePageUiContext, "HomePageUiContext");
}

export function useHomePageTaskContext() {
  return useRequiredContext(HomePageTaskContext, "HomePageTaskContext");
}

export function useHomePageChatContext() {
  return useRequiredContext(HomePageChatContext, "HomePageChatContext");
}
