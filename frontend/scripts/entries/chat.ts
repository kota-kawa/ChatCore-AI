import "../core/csrf";
import { initSharedDomRefs } from "../core/dom";
import { initChatUi } from "../chat/chat_ui";
import { initChatShare } from "../chat/chat_share";
import { initMainApp } from "../core/main";
import { initTaskManager } from "../setup/task_manager";
import { initNewPromptModal } from "../setup/new_prompt_modal";
import "../components/popup_menu";
import "../components/chat/popup_menu";
import "../components/user_icon";

function bootstrapChatEntry() {
  initSharedDomRefs();
  initChatUi();
  initChatShare();
  initTaskManager();
  initNewPromptModal();
  initMainApp();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrapChatEntry);
} else {
  bootstrapChatEntry();
}

export {};
