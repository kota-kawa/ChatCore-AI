// ホーム画面の AI エージェント用モーダルの開閉状態だけを持つ hook。use_home_page_controller.ts から使われる。
// Hook holding only the open / closed state of the home page's AI agent modal. Used by use_home_page_controller.ts.
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
