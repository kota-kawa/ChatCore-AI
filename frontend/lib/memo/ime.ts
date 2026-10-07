// 日本語変換の確定の Enter か。Safari は確定の keydown を変換終了の後に送るため isComposing が
// false になるが、keyCode は 229 のままなので、それも確定として扱う。
// Whether this Enter confirms an IME conversion. Safari sends that keydown after the composition
// has ended, so isComposing is false, but keyCode stays 229; treat that as a confirmation too.
export function isImeConfirmKey(event: { keyCode: number; nativeEvent: { isComposing: boolean } }): boolean {
  return event.nativeEvent.isComposing || event.keyCode === 229;
}
