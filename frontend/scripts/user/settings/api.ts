import { resilientFetch } from "../../core/resilient_fetch";
import { fetchJsonOrThrow } from "../../core/runtime_validation";

export function settingsFetchJsonOrThrow<TPayload>(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: Parameters<typeof fetchJsonOrThrow<TPayload>>[2],
) {
  return fetchJsonOrThrow<TPayload>(input, init, {
    ...options,
    fetchImpl: resilientFetch,
  });
}
