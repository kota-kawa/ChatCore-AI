import { useMemo, useRef, useState } from "react";

import { DEFAULT_MODEL, MODEL_OPTIONS } from "../../lib/chat_page/constants";

export function useHomePageUiState() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  const [isChatVisible, setIsChatVisible] = useState(false);
  const [setupInfo, setSetupInfo] = useState("");

  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [chatHeaderModelMenuOpen, setChatHeaderModelMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);

  const modelSelectRef = useRef<HTMLDivElement | null>(null);
  const chatHeaderModelSelectRef = useRef<HTMLDivElement | null>(null);

  const selectedModelLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.label ?? MODEL_OPTIONS[0]?.label ?? "";
  }, [selectedModel]);

  const selectedModelShortLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.shortLabel ?? MODEL_OPTIONS[0]?.shortLabel ?? "";
  }, [selectedModel]);

  return {
    loggedIn,
    setLoggedIn,
    authResolved,
    setAuthResolved,
    isChatVisible,
    setIsChatVisible,
    setupInfo,
    setSetupInfo,
    modelMenuOpen,
    setModelMenuOpen,
    chatHeaderModelMenuOpen,
    setChatHeaderModelMenuOpen,
    selectedModel,
    setSelectedModel,
    modelSelectRef,
    chatHeaderModelSelectRef,
    selectedModelLabel,
    selectedModelShortLabel,
  };
}
