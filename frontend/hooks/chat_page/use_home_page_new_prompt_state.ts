import { useRef, useState } from "react";

import type { PromptAssistController, PromptStatus } from "../../lib/chat_page/types";

export function useHomePageNewPromptState() {
  const [isNewPromptModalOpen, setIsNewPromptModalOpen] = useState(false);
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [newPromptTitle, setNewPromptTitle] = useState("");
  const [newPromptContent, setNewPromptContent] = useState("");
  const [newPromptInputExample, setNewPromptInputExample] = useState("");
  const [newPromptOutputExample, setNewPromptOutputExample] = useState("");
  const [newPromptStatus, setNewPromptStatus] = useState<PromptStatus>({ message: "", variant: "info" });
  const [isPromptSubmitting, setIsPromptSubmitting] = useState(false);

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
