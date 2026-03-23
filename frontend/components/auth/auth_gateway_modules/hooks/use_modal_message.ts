import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { MODAL_AUTO_CLOSE_MS, MODAL_CLOSE_ANIMATION_MS } from "../constants";

type TimerRef = MutableRefObject<ReturnType<typeof setTimeout> | null>;

function clearTimer(timerRef: TimerRef) {
  if (timerRef.current) {
    clearTimeout(timerRef.current);
    timerRef.current = null;
  }
}

export function useModalMessage() {
  const [modalMessage, setModalMessage] = useState<string | null>(null);
  const [isModalClosing, setIsModalClosing] = useState(false);

  const modalAutoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const modalCloseAnimationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hideModal = () => {
    setIsModalClosing(true);
    clearTimer(modalAutoCloseTimerRef);
    clearTimer(modalCloseAnimationTimerRef);

    modalCloseAnimationTimerRef.current = setTimeout(() => {
      setModalMessage(null);
      setIsModalClosing(false);
    }, MODAL_CLOSE_ANIMATION_MS);
  };

  const showModalMessage = (message: string) => {
    setModalMessage(message);
    setIsModalClosing(false);
    clearTimer(modalAutoCloseTimerRef);
    clearTimer(modalCloseAnimationTimerRef);

    modalAutoCloseTimerRef.current = setTimeout(() => {
      hideModal();
    }, MODAL_AUTO_CLOSE_MS);
  };

  useEffect(() => {
    return () => {
      clearTimer(modalAutoCloseTimerRef);
      clearTimer(modalCloseAnimationTimerRef);
    };
  }, []);

  return {
    hideModal,
    isModalClosing,
    modalMessage,
    showModalMessage
  };
}
