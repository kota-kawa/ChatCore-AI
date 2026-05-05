import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";

import { readSessionJson, writeSessionJson } from "../../lib/utils";

type DraggableModalProps = {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  initialX?: number;
  initialY?: number;
  positionStorageKey?: string;
};

type Position = { x: number; y: number };
const CLOSE_ANIMATION_MS = 320;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function DraggableModal({
  isOpen,
  onClose,
  title,
  children,
  initialX = 100,
  initialY = 100,
  positionStorageKey,
}: DraggableModalProps) {
  const [position, setPosition] = useState<Position>({ x: initialX, y: initialY });
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [hydrated, setHydrated] = useState(false);
  const [shouldRender, setShouldRender] = useState(isOpen);
  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (positionStorageKey) {
      const stored = readSessionJson<Position | null>(positionStorageKey, null);
      if (stored && isFiniteNumber(stored.x) && isFiniteNumber(stored.y)) {
        setPosition(stored);
      }
    }
    setHydrated(true);
  }, [positionStorageKey]);

  useEffect(() => {
    if (!hydrated || !positionStorageKey) return;
    writeSessionJson(positionStorageKey, position);
  }, [hydrated, positionStorageKey, position]);

  useEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setShouldRender(false);
    }, CLOSE_ANIMATION_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [isOpen]);

  const clampPosition = useCallback((nextPosition: { x: number; y: number }) => {
    const modal = modalRef.current;
    const modalWidth = modal?.offsetWidth || 360;
    const modalHeight = modal?.offsetHeight || 520;
    const margin = 12;
    const maxX = Math.max(margin, window.innerWidth - modalWidth - margin);
    const maxY = Math.max(margin, window.innerHeight - modalHeight - margin);

    return {
      x: Math.min(Math.max(nextPosition.x, margin), maxX),
      y: Math.min(Math.max(nextPosition.y, margin), maxY),
    };
  }, []);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest(".modal-close-btn")) return;

    setIsDragging(true);
    setDragOffset({
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    });
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest(".modal-close-btn")) return;
    if (event.pointerType === "mouse") return;

    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);
    setDragOffset({
      x: event.clientX - position.x,
      y: event.clientY - position.y,
    });
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging || event.pointerType === "mouse") return;
    setPosition(clampPosition({
      x: event.clientX - dragOffset.x,
      y: event.clientY - dragOffset.y,
    }));
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse") return;
    setIsDragging(false);
  };

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (isDragging) {
        setPosition(clampPosition({
          x: e.clientX - dragOffset.x,
          y: e.clientY - dragOffset.y,
        }));
      }
    },
    [isDragging, dragOffset, clampPosition]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    } else {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  useEffect(() => {
    if (!shouldRender) return undefined;

    const keepModalInViewport = () => {
      setPosition((current) => clampPosition(current));
    };

    keepModalInViewport();
    window.addEventListener("resize", keepModalInViewport);
    window.visualViewport?.addEventListener("resize", keepModalInViewport);
    window.visualViewport?.addEventListener("scroll", keepModalInViewport);

    return () => {
      window.removeEventListener("resize", keepModalInViewport);
      window.visualViewport?.removeEventListener("resize", keepModalInViewport);
      window.visualViewport?.removeEventListener("scroll", keepModalInViewport);
    };
  }, [shouldRender, clampPosition]);

  useEffect(() => {
    if (!isOpen) return undefined;

    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const timer = window.setTimeout(() => {
      const focusTarget = modalRef.current?.querySelector<HTMLElement>(
        "input:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex='-1'])"
      );
      focusTarget?.focus();
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) return undefined;
    const previouslyFocused = previouslyFocusedRef.current;
    if (previouslyFocused?.isConnected) {
      previouslyFocused.focus();
    }
    previouslyFocusedRef.current = null;
    return undefined;
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [isOpen, onClose]);

  if (!shouldRender) return null;

  return (
    <div
      ref={modalRef}
      className={`ai-agent-modal global-ai-agent-modal ${isOpen ? "is-open" : "is-closing"}`}
      role="dialog"
      aria-modal="false"
      aria-label={title || "AI エージェント"}
      style={{
        position: "fixed",
        left: `${position.x}px`,
        top: `${position.y}px`,
        zIndex: 1000,
        cursor: isDragging ? "grabbing" : "auto",
      }}
    >
      <div
        className="ai-agent-modal-header"
        onMouseDown={handleMouseDown}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        style={{ cursor: "grab", touchAction: "none" }}
      >
        <span className="ai-agent-modal-title">{title}</span>
        <button type="button" className="modal-close-btn" onClick={onClose} aria-label="AIエージェントを閉じる">
          <i className="bi bi-x-lg"></i>
        </button>
      </div>
      <div className="ai-agent-modal-content">
        {children}
      </div>
    </div>
  );
}
