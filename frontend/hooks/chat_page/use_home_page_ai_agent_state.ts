import { useState, useCallback } from "react";

export function useHomePageAiAgentState() {
  const [isAiAgentModalOpen, setIsAiAgentModalOpen] = useState(false);

  const openAiAgentModal = useCallback(() => {
    setIsAiAgentModalOpen(true);
  }, []);

  const closeAiAgentModal = useCallback(() => {
    setIsAiAgentModalOpen(false);
  }, []);

  const toggleAiAgentModal = useCallback(() => {
    setIsAiAgentModalOpen((prev) => !prev);
  }, []);

  return {
    isAiAgentModalOpen,
    openAiAgentModal,
    closeAiAgentModal,
    toggleAiAgentModal,
  };
}
