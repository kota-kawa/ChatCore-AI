import { useEffect, useMemo, useRef, useState } from "react";

import { DEFAULT_MODEL, MAX_SETUP_INFO_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import { STORAGE_KEYS } from "../../scripts/core/constants";

export type HomePageViewState = "setup" | "launching" | "chat";

function readStoredSetupInfo() {
  if (typeof window === "undefined") return "";

  try {
    return (localStorage.getItem(STORAGE_KEYS.setupInfoDraft) ?? "").slice(0, MAX_SETUP_INFO_LENGTH);
  } catch {
    return "";
  }
}

function readStoredTemporaryModeEnabled() {
  if (typeof window === "undefined") return false;

  try {
    return localStorage.getItem(STORAGE_KEYS.temporaryModeEnabled) === "1";
  } catch {
    return false;
  }
}

export function useHomePageUiState() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  const [pageViewState, setPageViewState] = useState<HomePageViewState>("setup");
  const [setupInfo, setSetupInfo] = useState("");
  const [temporaryModeEnabled, setTemporaryModeEnabled] = useState(false);
  const [storedSetupStateLoaded, setStoredSetupStateLoaded] = useState(false);

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

  useEffect(() => {
    setSetupInfo(readStoredSetupInfo());
    setTemporaryModeEnabled(readStoredTemporaryModeEnabled());
    setStoredSetupStateLoaded(true);
  }, []);

  useEffect(() => {
    if (!storedSetupStateLoaded) return;

    try {
      if (setupInfo.length > 0) {
        localStorage.setItem(STORAGE_KEYS.setupInfoDraft, setupInfo.slice(0, MAX_SETUP_INFO_LENGTH));
      } else {
        localStorage.removeItem(STORAGE_KEYS.setupInfoDraft);
      }
    } catch {
      // ignore localStorage failures
    }
  }, [setupInfo, storedSetupStateLoaded]);

  useEffect(() => {
    if (!storedSetupStateLoaded) return;

    try {
      localStorage.setItem(STORAGE_KEYS.temporaryModeEnabled, temporaryModeEnabled ? "1" : "0");
    } catch {
      // ignore localStorage failures
    }
  }, [storedSetupStateLoaded, temporaryModeEnabled]);

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
    temporaryModeEnabled,
    setTemporaryModeEnabled,
    storedSetupStateLoaded,
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
