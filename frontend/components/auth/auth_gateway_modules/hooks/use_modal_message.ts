import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { MODAL_AUTO_CLOSE_MS, MODAL_CLOSE_ANIMATION_MS } from "../constants";

type TimerRef = MutableRefObject<ReturnType<typeof setTimeout> | null>;

// タイマーが存在する場合にクリアし、refをnullにリセットする
// Clear the timer if it exists and reset the ref to null
function clearTimer(timerRef: TimerRef) {
  if (timerRef.current) {
    clearTimeout(timerRef.current);
    timerRef.current = null;
  }
}

// 認証ゲートウェイのメッセージモーダルの表示・非表示・自動クローズを管理するフック
// Hook that manages showing, hiding, and auto-closing the auth gateway message modal
export function useModalMessage() {
  // 表示するメッセージ（nullの場合はモーダル非表示）
  // Message to display (modal is hidden when null)
  const [modalMessage, setModalMessage] = useState<string | null>(null);
  // モーダルが閉じるアニメーション中かどうか
  // Whether the modal is in its closing animation
  const [isModalClosing, setIsModalClosing] = useState(false);

  // 自動クローズと閉じるアニメーションのタイマーref
  // Timer refs for auto-close and close animation
  const modalAutoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const modalCloseAnimationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // モーダルを閉じる（アニメーション後にメッセージをクリア）
  // Close the modal (clear message after animation completes)
  const hideModal = () => {
    setIsModalClosing(true);
    clearTimer(modalAutoCloseTimerRef);
    clearTimer(modalCloseAnimationTimerRef);

    modalCloseAnimationTimerRef.current = setTimeout(() => {
      setModalMessage(null);
      setIsModalClosing(false);
    }, MODAL_CLOSE_ANIMATION_MS);
  };

  // モーダルにメッセージを表示し、一定時間後に自動で閉じる
  // Show a message in the modal and auto-close it after a set duration
  const showModalMessage = (message: string) => {
    setModalMessage(message);
    setIsModalClosing(false);
    clearTimer(modalAutoCloseTimerRef);
    clearTimer(modalCloseAnimationTimerRef);

    modalAutoCloseTimerRef.current = setTimeout(() => {
      hideModal();
    }, MODAL_AUTO_CLOSE_MS);
  };

  // アンマウント時にタイマーをクリアしてメモリリークを防ぐ
  // Clear timers on unmount to prevent memory leaks
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
