import { useEffect, useState } from "react";

import { useTranslation } from "../contexts/locale_context";
import { readSessionJson, writeSessionJson } from "../lib/utils";
import { MiniChat } from "./chat_page/MiniChat";
import { DraggableModal } from "./ui/DraggableModal";

// セッションストレージのキー定数
// Session storage key constants
const OPEN_STATE_KEY = "globalAiAgent.isOpen";
const POSITION_STORAGE_KEY = "globalAiAgent.position";

// グローバルAIエージェントのフローティングボタンとモーダルを管理するコンポーネント
// Component that manages the global AI agent floating button and modal
export function GlobalAiAgent() {
  const { locale } = useTranslation();
  const agentLabel = locale === "en" ? "AI agent" : "AI エージェント";
  const launchLabel = locale === "en" ? "Open AI agent" : "AI エージェントを起動";
  // モーダルの開閉状態
  // Open/close state of the modal
  const [isOpen, setIsOpen] = useState(false);
  // SSRとのハイドレーション完了フラグ
  // Flag indicating hydration from SSR is complete
  const [hydrated, setHydrated] = useState(false);

  // マウント時にセッションストレージから開閉状態を復元する
  // On mount, restore the open/close state from session storage
  useEffect(() => {
    setIsOpen(readSessionJson<boolean>(OPEN_STATE_KEY, false));
    setHydrated(true);
  }, []);

  // 開閉状態が変化したらセッションストレージに保存する（ハイドレーション後のみ）
  // Save open/close state to session storage when it changes (only after hydration)
  useEffect(() => {
    if (!hydrated) return;
    writeSessionJson(OPEN_STATE_KEY, isOpen);
  }, [hydrated, isOpen]);

  return (
    <>
      {/* AIエージェント起動ボタン / AI agent launch button */}
      <button
        type="button"
        className="global-ai-agent-button"
        aria-label={launchLabel}
        aria-expanded={isOpen}
        data-tooltip={launchLabel}
        data-tooltip-placement="right"
        onClick={() => setIsOpen((current) => !current)}
      >
        <i className="bi bi-robot"></i>
      </button>

      {/* ドラッグ可能なAIエージェントモーダル / Draggable AI agent modal */}
      <DraggableModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title={agentLabel}
        initialX={20}
        initialY={100}
        positionStorageKey={POSITION_STORAGE_KEY}
      >
        <MiniChat />
      </DraggableModal>
    </>
  );
}
