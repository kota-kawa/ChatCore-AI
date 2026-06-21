import { SeoHead } from "../components/SeoHead";
import { ChatMainSection } from "../components/chat_page/chat_main_section";
import { ChatShareModal } from "../components/chat_page/modals/chat_share_modal";
import { NewPromptModal } from "../components/chat_page/modals/new_prompt_modal";
import { TaskDetailModal } from "../components/chat_page/modals/task_detail_modal";
import { TaskEditModal } from "../components/chat_page/modals/task_edit_modal";
import { SetupSection } from "../components/chat_page/setup_section";
import { ProjectSection } from "../components/chat_page/project_section";
import { NewProjectModal } from "../components/chat_page/modals/new_project_modal";
import { HomePageContextProvider } from "../contexts/chat_page/home_page_context";
import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";
import { absoluteUrl, DEFAULT_SEO_DESCRIPTION } from "../lib/seo";

const homeStructuredData = [
  {
    "@context": "https://schema.org",
    "@type": "WebApplication",
    name: "ChatCore-AI",
    applicationCategory: "ProductivityApplication",
    operatingSystem: "Web",
    url: absoluteUrl("/"),
    description: DEFAULT_SEO_DESCRIPTION,
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "JPY"
    }
  },
  {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "Chat Core",
    url: absoluteUrl("/"),
    inLanguage: "ja"
  }
];

// ホームページのメインコンポーネント
// Main component for the home page
export default function HomePage() {
  // ホームページのコントローラーフックを使用して状態とアクションを取得
  // Get state and actions using the home page controller hook
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

// チャットビュー内かどうかを判定
  // Check if we are in the chat view
  const isInChatView = pageViewState === "chat" || pageViewState === "launching";
  
  // フローティングUIのスタイル定義
  // Style definition for floating UI elements
  const floatingAuthUiStyle = {
    position: "fixed" as const,
    // チャット画面では visual viewport の offset-top を考慮してチャットヘッダー内に収める。
    // キーボードが開いている間は chat-page-shell が visual viewport に追従するが、
    // この要素は body 直下 fixed なので offset-top を加算して揃える。
    // In the chat screen, consider the visual viewport's offset-top to fit within the chat header.
    // While the keyboard is open, chat-page-shell follows the visual viewport,
    // but since this element is fixed directly under body, we add offset-top to align it.
    top: isInChatView
      ? "calc(var(--chat-visual-viewport-offset-top, 0px) + max(10px, env(safe-area-inset-top, 0px)))"
      : "max(10px, env(safe-area-inset-top, 0px))",
    right: "max(10px, env(safe-area-inset-right, 0px))",
    zIndex: "var(--z-floating-controls)"
  };

  return (
    <>
      <SeoHead
        title="ChatCore-AI | 日本語AIチャット・プロンプト共有・メモ管理"
        canonicalPath="/"
        structuredData={homeStructuredData}
      >
        <link rel="stylesheet" href="/static/css/pages/chat/page.css" />
      </SeoHead>

      <HomePageContextProvider controller={controller}>
        <div className="chat-page-shell cc-page-rise">
          {/* 検索エンジン・支援技術向けのページ見出し（視覚的には非表示） */}
          {/* Page heading for search engines and assistive tech (visually hidden) */}
          <h1 className="sr-only">ChatCore-AI ― 日本語AIチャット・プロンプト共有・メモ管理</h1>
          <action-menu></action-menu>

          <div
            id="auth-buttons"
            style={{
              ...floatingAuthUiStyle,
              display: authResolved && !loggedIn ? "" : "none"
            }}
          >
            {/* ログイン/登録ボタン */}
            {/* Login/Register button */}
            <button id="login-btn" className="auth-btn" onClick={() => {
              // ログインページへリダイレクト
              // Redirect to the login page
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

          {/* プロジェクト詳細オーバーレイ・新規プロジェクトモーダル（プロジェクト機能） */}
          {/* Project detail overlay and new-project modal (Projects feature) */}
          <ProjectSection />
          <NewProjectModal />

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
