import { useEffect, useState } from "react";

import { readSessionJson, writeSessionJson } from "../lib/utils";
import { MiniChat } from "./chat_page/MiniChat";
import { DraggableModal } from "./ui/DraggableModal";

const OPEN_STATE_KEY = "globalAiAgent.isOpen";
const POSITION_STORAGE_KEY = "globalAiAgent.position";

export function GlobalAiAgent() {
  const [isOpen, setIsOpen] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setIsOpen(readSessionJson<boolean>(OPEN_STATE_KEY, false));
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    writeSessionJson(OPEN_STATE_KEY, isOpen);
  }, [hydrated, isOpen]);

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
        positionStorageKey={POSITION_STORAGE_KEY}
      >
        <MiniChat />
      </DraggableModal>
    </>
  );
}
