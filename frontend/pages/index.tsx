import Head from "next/head";
import { ChatMainSection } from "../components/chat_page/chat_main_section";
import { ChatShareModal } from "../components/chat_page/modals/chat_share_modal";
import { NewPromptModal } from "../components/chat_page/modals/new_prompt_modal";
import { TaskDetailModal } from "../components/chat_page/modals/task_detail_modal";
import { TaskEditModal } from "../components/chat_page/modals/task_edit_modal";
import { SetupSection } from "../components/chat_page/setup_section";
import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";

export default function HomePage() {
  const {
    loggedIn,
    isChatVisible,
    setupInfo,
    selectedModel,
    modelMenuOpen,
    selectedModelLabel,
    tasks,
    isTaskOrderEditing,
    isNewPromptModalOpen,
    tasksExpanded,
    showTaskToggleButton,
    visibleTaskCountText,
    draggingTaskIndex,
    modelSelectRef,
    setSetupInfo,
    setSelectedModel,
    setModelMenuOpen,
    toggleTaskOrderEditing,
    closeNewPromptModal,
    openNewPromptModal,
    handleTaskDragStart,
    handleTaskDragOver,
    handleTaskDragEnd,
    handleTaskCardLaunch,
    handleTaskDelete,
    openTaskEditModal,
    setTaskDetail,
    setTasksExpanded,
    handleAccessChat,
    chatHeaderModelMenuOpen,
    selectedModelShortLabel,
    hasCurrentRoom,
    sidebarOpen,
    chatRooms,
    currentRoomId,
    openRoomActionsFor,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    messages,
    chatInput,
    isGenerating,
    chatHeaderModelSelectRef,
    chatMessagesRef,
    showSetupForm,
    setChatHeaderModelMenuOpen,
    openShareModal,
    handleNewChat,
    switchChatRoom,
    setOpenRoomActionsFor,
    handleRenameRoom,
    handleDeleteRoom,
    setSidebarOpen,
    loadOlderChatHistory,
    setChatInput,
    handleChatInputKeyDown,
    handleSendMessage,
    taskDetail,
    isPromptSubmitting,
    guardrailEnabled,
    newPromptTitle,
    newPromptContent,
    newPromptInputExample,
    newPromptOutputExample,
    newPromptStatus,
    titleInputRef,
    contentInputRef,
    inputExampleRef,
    outputExampleRef,
    newPromptAssistRootRef,
    handlePromptSubmit,
    setGuardrailEnabled,
    setNewPromptTitle,
    setNewPromptContent,
    setNewPromptInputExample,
    setNewPromptOutputExample,
    taskEditModalOpen,
    taskEditForm,
    closeTaskEditModal,
    setTaskEditForm,
    handleTaskEditSave,
    shareModalOpen,
    shareStatus,
    shareUrl,
    shareLoading,
    supportsNativeShare,
    shareXUrl,
    shareLineUrl,
    shareFacebookUrl,
    closeShareModal,
    copyShareLink,
    shareWithNativeSheet,
  } = useHomePageController();

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

        <SetupSection
          isChatVisible={isChatVisible}
          loggedIn={loggedIn}
          setupInfo={setupInfo}
          selectedModel={selectedModel}
          modelMenuOpen={modelMenuOpen}
          selectedModelLabel={selectedModelLabel}
          tasks={tasks}
          isTaskOrderEditing={isTaskOrderEditing}
          isNewPromptModalOpen={isNewPromptModalOpen}
          tasksExpanded={tasksExpanded}
          showTaskToggleButton={showTaskToggleButton}
          visibleTaskCountText={visibleTaskCountText}
          draggingTaskIndex={draggingTaskIndex}
          modelSelectRef={modelSelectRef}
          setSetupInfo={setSetupInfo}
          setSelectedModel={setSelectedModel}
          setModelMenuOpen={setModelMenuOpen}
          toggleTaskOrderEditing={toggleTaskOrderEditing}
          closeNewPromptModal={closeNewPromptModal}
          openNewPromptModal={openNewPromptModal}
          handleTaskDragStart={handleTaskDragStart}
          handleTaskDragOver={handleTaskDragOver}
          handleTaskDragEnd={handleTaskDragEnd}
          handleTaskCardLaunch={handleTaskCardLaunch}
          handleTaskDelete={handleTaskDelete}
          openTaskEditModal={openTaskEditModal}
          setTaskDetail={setTaskDetail}
          setTasksExpanded={setTasksExpanded}
          handleAccessChat={handleAccessChat}
        />

        <ChatMainSection
          isChatVisible={isChatVisible}
          chatHeaderModelMenuOpen={chatHeaderModelMenuOpen}
          selectedModel={selectedModel}
          selectedModelShortLabel={selectedModelShortLabel}
          hasCurrentRoom={hasCurrentRoom}
          sidebarOpen={sidebarOpen}
          chatRooms={chatRooms}
          currentRoomId={currentRoomId}
          openRoomActionsFor={openRoomActionsFor}
          historyHasMore={historyHasMore}
          historyNextBeforeId={historyNextBeforeId}
          isLoadingOlder={isLoadingOlder}
          messages={messages}
          chatInput={chatInput}
          isGenerating={isGenerating}
          chatHeaderModelSelectRef={chatHeaderModelSelectRef}
          chatMessagesRef={chatMessagesRef}
          showSetupForm={showSetupForm}
          setChatHeaderModelMenuOpen={setChatHeaderModelMenuOpen}
          setSelectedModel={setSelectedModel}
          openShareModal={openShareModal}
          handleNewChat={handleNewChat}
          switchChatRoom={switchChatRoom}
          setOpenRoomActionsFor={setOpenRoomActionsFor}
          handleRenameRoom={handleRenameRoom}
          handleDeleteRoom={handleDeleteRoom}
          setSidebarOpen={setSidebarOpen}
          loadOlderChatHistory={loadOlderChatHistory}
          setChatInput={setChatInput}
          handleChatInputKeyDown={handleChatInputKeyDown}
          handleSendMessage={handleSendMessage}
        />

        <TaskDetailModal
          taskDetail={taskDetail}
          onClose={() => {
            setTaskDetail(null);
          }}
        />

        <NewPromptModal
          isOpen={isNewPromptModalOpen}
          isPromptSubmitting={isPromptSubmitting}
          guardrailEnabled={guardrailEnabled}
          newPromptTitle={newPromptTitle}
          newPromptContent={newPromptContent}
          newPromptInputExample={newPromptInputExample}
          newPromptOutputExample={newPromptOutputExample}
          newPromptStatus={newPromptStatus}
          titleInputRef={titleInputRef}
          contentInputRef={contentInputRef}
          inputExampleRef={inputExampleRef}
          outputExampleRef={outputExampleRef}
          newPromptAssistRootRef={newPromptAssistRootRef}
          onClose={closeNewPromptModal}
          onSubmit={(event) => {
            void handlePromptSubmit(event);
          }}
          setGuardrailEnabled={setGuardrailEnabled}
          setNewPromptTitle={setNewPromptTitle}
          setNewPromptContent={setNewPromptContent}
          setNewPromptInputExample={setNewPromptInputExample}
          setNewPromptOutputExample={setNewPromptOutputExample}
        />

        <TaskEditModal
          taskEditModalOpen={taskEditModalOpen}
          taskEditForm={taskEditForm}
          closeTaskEditModal={closeTaskEditModal}
          setTaskEditForm={setTaskEditForm}
          onSave={() => {
            void handleTaskEditSave();
          }}
        />

        <ChatShareModal
          shareModalOpen={shareModalOpen}
          shareStatus={shareStatus}
          shareUrl={shareUrl}
          shareLoading={shareLoading}
          supportsNativeShare={supportsNativeShare}
          shareXUrl={shareXUrl}
          shareLineUrl={shareLineUrl}
          shareFacebookUrl={shareFacebookUrl}
          closeShareModal={closeShareModal}
          copyShareLink={() => {
            void copyShareLink();
          }}
          shareWithNativeSheet={() => {
            void shareWithNativeSheet();
          }}
        />
      </div>
    </>
  );
}
