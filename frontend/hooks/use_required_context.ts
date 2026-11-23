// Provider の外で使われたら原因が分かるエラーを投げる、Context 取得の共通 hook。画面ごとの Context 群の取得 hook が使う。
// Shared hook for reading a context that throws a descriptive error outside its provider; used by the per-page context accessors.
import { useContext, type Context } from "react";

export function useRequiredContext<T>(context: Context<T | null>, contextName: string, providerName: string): T {
  const value = useContext(context);
  if (!value) {
    throw new Error(`${contextName} must be used within ${providerName}.`);
  }
  return value;
}
