import { useState } from "react";

import { MiniChat } from "./chat_page/MiniChat";
import { DraggableModal } from "./ui/DraggableModal";

export function GlobalAiAgent() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="global-ai-agent-button"
        aria-label="AI エージェントを起動"
        aria-expanded={isOpen}
        data-tooltip="AI エージェントを起動"
        data-tooltip-placement="right"
        onClick={() => setIsOpen((current) => !current)}
      >
        <i className="bi bi-robot"></i>
      </button>

      <DraggableModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title="AI エージェント"
        initialX={20}
        initialY={100}
      >
        <MiniChat />
      </DraggableModal>
    </>
  );
}
