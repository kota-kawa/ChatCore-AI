export type Position = { x: number; y: number };

export type Size = { width: number; height: number };

export type ViewportBounds = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export type Rect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

const POSITION_MARGIN = 12;
const AVOIDANCE_GAP = 12;

function positionsEqual(first: Position, second: Position) {
  return first.x === second.x && first.y === second.y;
}

function positionToRect(position: Position, size: Size): Rect {
  return {
    left: position.x,
    top: position.y,
    right: position.x + size.width,
    bottom: position.y + size.height,
  };
}

function overlapArea(first: Rect, second: Rect) {
  const overlapWidth = Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left));
  const overlapHeight = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top));
  return overlapWidth * overlapHeight;
}

export function clampModalPosition(position: Position, modalSize: Size, viewport: ViewportBounds): Position {
  const minX = viewport.left + POSITION_MARGIN;
  const minY = viewport.top + POSITION_MARGIN;
  const maxX = Math.max(minX, viewport.left + viewport.width - modalSize.width - POSITION_MARGIN);
  const maxY = Math.max(minY, viewport.top + viewport.height - modalSize.height - POSITION_MARGIN);

  return {
    x: Math.min(Math.max(position.x, minX), maxX),
    y: Math.min(Math.max(position.y, minY), maxY),
  };
}

export function positionModalAwayFromRect(
  position: Position,
  modalSize: Size,
  viewport: ViewportBounds,
  avoidedRect?: Rect,
): Position {
  const clampedPosition = clampModalPosition(position, modalSize, viewport);
  if (!avoidedRect || avoidedRect.right <= avoidedRect.left || avoidedRect.bottom <= avoidedRect.top) {
    return clampedPosition;
  }

  const paddedAvoidedRect = {
    left: avoidedRect.left - AVOIDANCE_GAP,
    top: avoidedRect.top - AVOIDANCE_GAP,
    right: avoidedRect.right + AVOIDANCE_GAP,
    bottom: avoidedRect.bottom + AVOIDANCE_GAP,
  };
  if (overlapArea(positionToRect(clampedPosition, modalSize), paddedAvoidedRect) === 0) {
    return clampedPosition;
  }

  const candidates = [
    { x: avoidedRect.right + AVOIDANCE_GAP, y: clampedPosition.y },
    { x: avoidedRect.left - modalSize.width - AVOIDANCE_GAP, y: clampedPosition.y },
    { x: clampedPosition.x, y: avoidedRect.top - modalSize.height - AVOIDANCE_GAP },
    { x: clampedPosition.x, y: avoidedRect.bottom + AVOIDANCE_GAP },
  ].map((candidate) => clampModalPosition(candidate, modalSize, viewport));

  return candidates.reduce((best, candidate) => {
    const bestOverlap = overlapArea(positionToRect(best, modalSize), paddedAvoidedRect);
    const candidateOverlap = overlapArea(positionToRect(candidate, modalSize), paddedAvoidedRect);
    if (candidateOverlap !== bestOverlap) return candidateOverlap < bestOverlap ? candidate : best;

    const bestDistance = (best.x - clampedPosition.x) ** 2 + (best.y - clampedPosition.y) ** 2;
    const candidateDistance = (candidate.x - clampedPosition.x) ** 2 + (candidate.y - clampedPosition.y) ** 2;
    return candidateDistance < bestDistance ? candidate : best;
  }, clampedPosition);
}

export function keepPositionIfUnchanged(current: Position, next: Position) {
  return positionsEqual(current, next) ? current : next;
}
