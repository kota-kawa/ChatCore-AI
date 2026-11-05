// ドラッグできるモーダルの位置の計算。画面の内側に収め、避けたい領域（ほかの要素の矩形）と重ならない位置を選ぶ。
// Position calculations for the draggable modal: keep it inside the viewport and pick a spot that does not overlap an area to avoid.
// Used by components/ui/DraggableModal.tsx.

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

// 画面の端からモーダルまで空ける余白（px）。
// Margin (px) kept between the viewport edge and the modal.
const POSITION_MARGIN = 12;
// 避ける対象の領域とモーダルのあいだに空ける間隔（px）。
// Gap (px) kept between the modal and the area it avoids.
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

// 2 つの矩形が重なる面積。重ならなければ 0。
// Area where two rectangles overlap; 0 when they do not.
function overlapArea(first: Rect, second: Rect) {
  const overlapWidth = Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left));
  const overlapHeight = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top));
  return overlapWidth * overlapHeight;
}

// モーダルが余白を残して画面内に収まるよう、位置を補正する。画面より大きい場合は左上の余白位置に寄せる。
// Adjusts the position so the modal stays inside the viewport with a margin; if it is larger than the viewport, it is pinned to the top-left margin.
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

// 避けたい矩形と重ならない位置を返す。重なるときは、その矩形の右・左・上・下に置いた 4 つの候補から、重なりが最も小さいものを選ぶ（同じなら元の位置に近いほう）。
// Returns a position that does not overlap the rectangle to avoid. When it would overlap, it tries four candidates (right, left, above, below) and picks the one with the least overlap, then the one closest to the original position.
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

// 位置が同じなら以前のオブジェクトをそのまま返し、React が無駄な再描画をしないようにする。
// Returns the existing object when the position is unchanged so React does not re-render needlessly.
export function keepPositionIfUnchanged(current: Position, next: Position) {
  return positionsEqual(current, next) ? current : next;
}
