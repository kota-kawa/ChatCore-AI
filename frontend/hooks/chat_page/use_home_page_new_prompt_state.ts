// ホーム画面の「新規タスク（プロンプト）追加」モーダルのフォーム値、状態表示、入力欄の ref を宣言して返す hook。use_home_page_controller.ts から使われる。
// Hook declaring the form values, status message and input refs of the home page's "add new task (prompt)" modal. Used by use_home_page_controller.ts.
import { useRef, useState } from "react";

import type { PromptAssistController, PromptStatus } from "../../lib/chat_page/types";

export function useHomePageNewPromptState() {
  const [isNewPromptModalOpen, setIsNewPromptModalOpen] = useState(false);
  // オンのときだけ入力例・出力例を送信する（use_home_page_controller.ts の handlePromptSubmit を参照）
  // Input / output examples are submitted only when this is on (see handlePromptSubmit in use_home_page_controller.ts)
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [newPromptTitle, setNewPromptTitle] = useState("");
  const [newPromptContent, setNewPromptContent] = useState("");
  const [newPromptInputExample, setNewPromptInputExample] = useState("");
  const [newPromptOutputExample, setNewPromptOutputExample] = useState("");
  const [newPromptStatus, setNewPromptStatus] = useState<PromptStatus>({ message: "", variant: "info" });
  const [isPromptSubmitting, setIsPromptSubmitting] = useState(false);

  // AI 補助（prompt assist）の初期化に使う、モーダル内の要素と入力欄への参照
  // Refs to the modal element and input fields used to initialize AI assistance (prompt assist)
  const newPromptAssistRootRef = useRef<HTMLDivElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const contentInputRef = useRef<HTMLTextAreaElement | null>(null);
  const inputExampleRef = useRef<HTMLTextAreaElement | null>(null);
  const outputExampleRef = useRef<HTMLTextAreaElement | null>(null);
  const promptAssistControllerRef = useRef<PromptAssistController | null>(null);

  return {
    isNewPromptModalOpen,
    setIsNewPromptModalOpen,
    guardrailEnabled,
    setGuardrailEnabled,
    newPromptTitle,
    setNewPromptTitle,
    newPromptContent,
    setNewPromptContent,
    newPromptInputExample,
    setNewPromptInputExample,
    newPromptOutputExample,
    setNewPromptOutputExample,
    newPromptStatus,
    setNewPromptStatus,
    isPromptSubmitting,
    setIsPromptSubmitting,
    newPromptAssistRootRef,
    titleInputRef,
    contentInputRef,
    inputExampleRef,
    outputExampleRef,
    promptAssistControllerRef,
  };
}
