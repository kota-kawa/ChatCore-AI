// className に渡す文字列を、未指定（undefined・false・空文字）を除いて半角スペースでつなぐ。
// Joins class names with a space, skipping unset values (undefined, false, empty string).
export function joinClasses(...classes: Array<string | undefined | false>): string {
  return classes.filter(Boolean).join(" ");
}
