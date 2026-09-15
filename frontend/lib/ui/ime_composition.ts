// IME変換確定のEnterを送信と誤認しないための判定（Reactに依存しない中核）
// Core rules that keep the Enter which confirms an IME conversion from being read as "send"
// (no React dependency, so the vanilla DOM modals can share them)

// Safari（macOS）と Android の Gboard は、変換確定のEnterで compositionend を keydown より
// 先に発火させるため、keydown の時点では isComposing が false になっている。同じ一度の
// キー入力から生まれた2つのイベントなので間隔はミリ秒未満で、この猶予内のEnterは
// 変換確定として扱う。
// Safari on macOS and Gboard on Android fire compositionend before the keydown of the very same
// key press, so isComposing is already false by the time the handler runs. Both events come from
// one press and land within a millisecond of each other, so an Enter inside this window is the
// confirmation rather than a send.
export const COMPOSITION_END_GRACE_MS = 50;

// 変換中の keydown に対してブラウザが返す値。Chrome/Edge は keyCode 229、
// Firefox は key === "Process" を返す。
// Values browsers report for a keydown that belongs to an in-flight conversion:
// Chrome/Edge use keyCode 229, Firefox uses key === "Process".
const IME_KEY_CODE = 229;
const IME_KEY_NAME = "Process";

// ASCII の範囲外の文字を含むかどうかの判定に使う。
// Used to tell whether a commit contains anything outside the ASCII range.
const NON_ASCII_PATTERN = /[^\x20-\x7E]/;

type CompositionKeyEvent = {
  key: string;
  keyCode?: number;
  isComposing?: boolean;
};

// ブラウザ自身が「変換中の入力だ」と言っているか
// Whether the browser itself reports the key press as part of a conversion
export function isImeCompositionKeyEvent(event: CompositionKeyEvent): boolean {
  if (event.isComposing) return true;
  if (event.keyCode === IME_KEY_CODE) return true;
  return event.key === IME_KEY_NAME;
}

// 猶予を張るのは非ASCIIを確定したときだけ。Android のソフトキーボードは英単語の入力でも
// 送信キーの直前に compositionend を出すため、無条件に張ると英語入力の送信が効かなくなる。
// The window is armed only for a non-ASCII commit. Android soft keyboards emit compositionend
// just before the send key even for plain English words, so arming it unconditionally would
// swallow the send on English input.
export function shouldArmCompositionGrace(data: string | null | undefined): boolean {
  if (!data) return false;
  return NON_ASCII_PATTERN.test(data);
}

// 変換確定の直後に届いたキー入力かどうか
// Whether the key press landed immediately after a conversion was committed
export function isWithinCompositionGrace(keyTimeStamp: number, compositionEndedAt: number): boolean {
  return keyTimeStamp - compositionEndedAt < COMPOSITION_END_GRACE_MS;
}
