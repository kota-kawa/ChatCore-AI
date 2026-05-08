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
