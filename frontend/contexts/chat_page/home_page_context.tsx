import { createContext, useContext, type Context, type ReactNode } from "react";

type HomePageControllerState =
  ReturnType<typeof import("../../hooks/chat_page/use_home_page_controller").useHomePageController>;

type HomePageUiContextValue = Pick<
  HomePageControllerState,
  | "loggedIn"
  | "isChatVisible"
  | "setupInfo"
  | "selectedModel"
  | "modelMenuOpen"
  | "selectedModelLabel"
  | "selectedModelShortLabel"
  | "modelSelectRef"
  | "chatHeaderModelMenuOpen"
  | "chatHeaderModelSelectRef"
  | "setSetupInfo"
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
>;

type HomePageChatContextValue = Pick<
  HomePageControllerState,
  | "handleAccessChat"
  | "hasCurrentRoom"
  | "sidebarOpen"
  | "chatRooms"
  | "currentRoomId"
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
  const uiValue: HomePageUiContextValue = {
    loggedIn: controller.loggedIn,
    isChatVisible: controller.isChatVisible,
    setupInfo: controller.setupInfo,
    selectedModel: controller.selectedModel,
    modelMenuOpen: controller.modelMenuOpen,
    selectedModelLabel: controller.selectedModelLabel,
    selectedModelShortLabel: controller.selectedModelShortLabel,
    modelSelectRef: controller.modelSelectRef,
    chatHeaderModelMenuOpen: controller.chatHeaderModelMenuOpen,
    chatHeaderModelSelectRef: controller.chatHeaderModelSelectRef,
    setSetupInfo: controller.setSetupInfo,
    setSelectedModel: controller.setSelectedModel,
    setModelMenuOpen: controller.setModelMenuOpen,
    setChatHeaderModelMenuOpen: controller.setChatHeaderModelMenuOpen,
    showSetupForm: controller.showSetupForm,
  };

  const taskValue: HomePageTaskContextValue = {
    tasks: controller.tasks,
    isTaskOrderEditing: controller.isTaskOrderEditing,
    isNewPromptModalOpen: controller.isNewPromptModalOpen,
    tasksExpanded: controller.tasksExpanded,
    showTaskToggleButton: controller.showTaskToggleButton,
    visibleTaskCountText: controller.visibleTaskCountText,
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
  };

  const chatValue: HomePageChatContextValue = {
    handleAccessChat: controller.handleAccessChat,
    hasCurrentRoom: controller.hasCurrentRoom,
    sidebarOpen: controller.sidebarOpen,
    chatRooms: controller.chatRooms,
    currentRoomId: controller.currentRoomId,
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
  };

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
