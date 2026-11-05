// /api/current_user の応答からログイン状態を読み取る補助。認証エラー（401/403）は専用の例外にして、一時的な失敗と区別する。
// Helper that reads the login state from a /api/current_user response; auth errors (401/403) throw a dedicated error so they can be told apart from transient failures.
export class CurrentUserAuthError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(status === 401 ? "ログインセッションが切れました。" : "認証状態を確認できませんでした。");
    this.name = "CurrentUserAuthError";
    this.status = status;
  }
}

export async function readCurrentUserLoggedIn(response: Response) {
  if (response.status === 401 || response.status === 403) {
    throw new CurrentUserAuthError(response.status);
  }

  if (!response.ok) {
    throw new Error(`current_user request failed with status ${response.status}`);
  }

  const data = (await response.json().catch(() => ({}))) as { logged_in?: unknown };
  return Boolean(data?.logged_in);
}
