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
  const modalRef = useRef<HTMLDivElement>(null);

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
    if (!isOpen) return undefined;

    const keepModalInViewport = () => {
      setPosition((current) => clampPosition(current));
    };

    keepModalInViewport();
    window.addEventListener("resize", keepModalInViewport);

    return () => {
      window.removeEventListener("resize", keepModalInViewport);
    };
  }, [isOpen, clampPosition]);

  if (!isOpen) return null;

  return (
    <div
      ref={modalRef}
      className="ai-agent-modal global-ai-agent-modal"
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
      <div className="ai-agent-modal-header" onMouseDown={handleMouseDown} style={{ cursor: "grab" }}>
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
