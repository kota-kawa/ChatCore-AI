import { useMemo, useRef, useState } from "react";

import { DEFAULT_MODEL, MODEL_OPTIONS } from "../../lib/chat_page/constants";

export type HomePageViewState = "setup" | "launching" | "chat";

export function useHomePageUiState() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  const [pageViewState, setPageViewState] = useState<HomePageViewState>("setup");
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

  const isChatVisible = pageViewState !== "setup";
  const isSetupVisible = pageViewState !== "chat";
  const isChatLaunching = pageViewState === "launching";

  return {
    loggedIn,
    setLoggedIn,
    authResolved,
    setAuthResolved,
    pageViewState,
    setPageViewState,
    isChatVisible,
    isSetupVisible,
    isChatLaunching,
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
