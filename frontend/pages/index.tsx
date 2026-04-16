import Head from "next/head";
import { ChatMainSection } from "../components/chat_page/chat_main_section";
import { ChatShareModal } from "../components/chat_page/modals/chat_share_modal";
import { NewPromptModal } from "../components/chat_page/modals/new_prompt_modal";
import { TaskDetailModal } from "../components/chat_page/modals/task_detail_modal";
import { TaskEditModal } from "../components/chat_page/modals/task_edit_modal";
import { SetupSection } from "../components/chat_page/setup_section";
import { HomePageContextProvider } from "../contexts/chat_page/home_page_context";
import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";

export default function HomePage() {
  const controller = useHomePageController();

  const {
    loggedIn,
    authResolved,
    pageViewState,
    isNewPromptModalOpen,
    closeNewPromptModal,
    setTaskDetail,
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
  } = controller;

  const floatingAuthUiStyle = {
    position: "fixed" as const,
    top: "max(10px, env(safe-area-inset-top, 0px))",
    right: "max(10px, env(safe-area-inset-right, 0px))",
    zIndex: 2000
  };

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

      <HomePageContextProvider controller={controller}>
        <div className="chat-page-shell">
          <action-menu></action-menu>

          <div
            id="auth-buttons"
            style={{
              ...floatingAuthUiStyle,
              display: authResolved && !loggedIn ? "" : "none"
            }}
          >
            <button id="login-btn" className="auth-btn" onClick={() => {
              window.location.href = "/login";
            }}>
              <i className="bi bi-person-circle"></i>
              <span>ログイン / 登録</span>
            </button>
          </div>

          <user-icon
            id="userIcon"
            style={{
              ...floatingAuthUiStyle,
              display: authResolved && loggedIn ? "" : "none"
            }}
          ></user-icon>

          <div
            className="chat-page-stage"
            data-view={pageViewState}
            aria-busy={pageViewState === "launching" ? "true" : undefined}
          >
            <SetupSection />

            <ChatMainSection />
          </div>

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
      </HomePageContextProvider>
    </>
  );
}
