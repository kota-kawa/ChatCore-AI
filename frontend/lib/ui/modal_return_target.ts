// カードから開くモーダルが、閉じるときに元のカードへ縮んで戻るための取り決めと計算。
// カード側は `data-modal-origin` に `modalOriginKey()` の値を付け、モーダル側は同じ値を
// ModalShell の `returnTo` に渡す。ModalShell は閉じる瞬間にこの値でカードを探し、
// パネルからカードまでの移動量と縮尺を CSS 変数として外殻に載せる。
// Contract and math for modals opened from a card that shrink back into that card on close.
// The card carries `data-modal-origin` set to `modalOriginKey()`, and the modal passes the
// same value as ModalShell's `returnTo`. When closing, ModalShell looks the card up by that
// value and puts the panel-to-card offset and scale on the overlay as CSS variables.

export const MODAL_ORIGIN_ATTRIBUTE = "data-modal-origin";

type RectLike = Pick<DOMRect, "left" | "top" | "width" | "height">;

type ViewportSize = { width: number; height: number };

export type ModalReturnMotion = {
  x: number;
  y: number;
  scaleX: number;
  scaleY: number;
};

// 種類と ID から戻り先の目印を作る（同じ ID が別種類のカードと衝突しないよう種類を前に付ける）。
// ID が未確定（楽観的に追加したカードなど）なら目印を作らず、閉じるときはその場で薄れる。
// Builds the origin marker from a kind and an ID; the kind prefix keeps IDs of different card types apart.
// Without a settled ID (e.g. an optimistically inserted card) there is no marker and the modal fades in place.
export function modalOriginKey(kind: string, id: string | number | null | undefined): string | null {
  if (id === null || id === undefined || id === "") return null;
  return `${kind}:${id}`;
}

function isVisibleIn(rect: RectLike, viewport: ViewportSize) {
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    rect.left < viewport.width &&
    rect.top < viewport.height &&
    rect.left + rect.width > 0 &&
    rect.top + rect.height > 0
  );
}

function currentViewport(): ViewportSize {
  return { width: window.innerWidth, height: window.innerHeight };
}

// 目印の付いたカードのうち、画面に見えている最初の 1 枚を返す。
// 同じカードが複数の一覧に並ぶことがあるため、見えているものを選ぶ。
// Returns the first card carrying the marker that is visible on screen. The same item can
// appear in several lists, so only a visible one is picked.
export function findModalOrigin(key: string): HTMLElement | null {
  const viewport = currentViewport();
  const candidates = document.querySelectorAll<HTMLElement>(`[${MODAL_ORIGIN_ATTRIBUTE}]`);
  for (const candidate of candidates) {
    if (candidate.getAttribute(MODAL_ORIGIN_ATTRIBUTE) !== key) continue;
    if (isVisibleIn(candidate.getBoundingClientRect(), viewport)) return candidate;
  }
  return null;
}

// パネルの左上を原点に、パネルをカードの位置と大きさへ重ねる移動量と縮尺を返す。
// カードが画面外か大きさを持たないときは null（呼び出し側はその場で薄れる動きにする）。
// Returns the offset and scale that lay the panel (transform origin at its top-left) over the
// card. Null when the card is off screen or has no size, so the caller falls back to an in-place fade.
export function computeModalReturnMotion(
  panel: RectLike,
  target: RectLike,
  viewport: ViewportSize = currentViewport(),
): ModalReturnMotion | null {
  if (panel.width <= 0 || panel.height <= 0) return null;
  if (!isVisibleIn(target, viewport)) return null;
  return {
    x: target.left - panel.left,
    y: target.top - panel.top,
    scaleX: target.width / panel.width,
    scaleY: target.height / panel.height,
  };
}
