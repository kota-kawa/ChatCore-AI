import { browserSupportsPasskeys, PasskeyCancelledError, registerPasskey } from "../../core/passkeys";
import { escapeHtml } from "./utils";

type PasskeyModuleOptions = {
  passkeySupportStatusEl: HTMLElement | null;
  passkeyListEl: HTMLElement | null;
  registerPasskeyBtn: HTMLButtonElement | null;
  refreshPasskeysBtn: HTMLButtonElement | null;
};

export function setupPasskeyModule(options: PasskeyModuleOptions) {
  const { passkeySupportStatusEl, passkeyListEl, registerPasskeyBtn, refreshPasskeysBtn } = options;

  const formatDateTime = (value: unknown) => {
    if (typeof value !== "string" || !value) return "未使用";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "未使用" : date.toLocaleString();
  };

  const renderPasskeys = (passkeys: unknown[]) => {
    if (!passkeyListEl) return;

    if (passkeys.length === 0) {
      passkeyListEl.innerHTML = '<p class="passkey-empty">まだPasskeyは登録されていません。</p>';
      return;
    }

    passkeyListEl.innerHTML = passkeys
      .map((rawPasskey) => {
        const passkey = typeof rawPasskey === "object" && rawPasskey !== null
          ? (rawPasskey as Record<string, unknown>)
          : {};
        const id = Number(passkey.id);
        const label = typeof passkey.label === "string" && passkey.label.trim()
          ? passkey.label.trim()
          : "保存済みPasskey";
        const deviceType = typeof passkey.credential_device_type === "string"
          ? passkey.credential_device_type
          : "不明";
        const backedUp = passkey.credential_backed_up ? "あり" : "なし";

        return `
          <div class="passkey-item">
            <div>
              <strong>${escapeHtml(label)}</strong>
              <div class="passkey-meta">
                端末種別: ${escapeHtml(deviceType)}<br>
                バックアップ: ${escapeHtml(backedUp)}<br>
                作成日時: ${escapeHtml(formatDateTime(passkey.created_at))}<br>
                最終利用: ${escapeHtml(formatDateTime(passkey.last_used_at))}
              </div>
            </div>
            <button type="button" class="secondary-button delete-passkey-btn" data-passkey-id="${escapeHtml(id)}">
              削除
            </button>
          </div>
        `;
      })
      .join("");
  };

  async function loadPasskeys() {
    if (!passkeySupportStatusEl || !passkeyListEl) return;

    if (!browserSupportsPasskeys()) {
      passkeySupportStatusEl.textContent = "このブラウザではPasskeyを利用できません。";
      if (registerPasskeyBtn) registerPasskeyBtn.disabled = true;
      if (refreshPasskeysBtn) refreshPasskeysBtn.disabled = true;
      renderPasskeys([]);
      return;
    }

    passkeySupportStatusEl.textContent = "このブラウザはPasskeyに対応しています。";

    try {
      const response = await fetch("/api/passkeys", { credentials: "same-origin" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === "fail") {
        throw new Error(typeof data.error === "string" ? data.error : "Passkey一覧の取得に失敗しました。");
      }
      renderPasskeys(Array.isArray(data.passkeys) ? data.passkeys : []);
    } catch (error) {
      renderPasskeys([]);
      alert((error as Error).message);
    }
  }

  registerPasskeyBtn?.addEventListener("click", async () => {
    registerPasskeyBtn.disabled = true;
    try {
      await registerPasskey();
      alert("Passkeyを追加しました。");
      await loadPasskeys();
    } catch (error) {
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      alert((error as Error).message);
    } finally {
      registerPasskeyBtn.disabled = false;
    }
  });

  refreshPasskeysBtn?.addEventListener("click", () => {
    void loadPasskeys();
  });

  passkeyListEl?.addEventListener("click", async (event) => {
    const target = event.target instanceof HTMLElement ? event.target.closest(".delete-passkey-btn") : null;
    if (!(target instanceof HTMLButtonElement)) return;

    const rawPasskeyId = target.dataset.passkeyId;
    if (!rawPasskeyId) return;
    if (!window.confirm("このPasskeyを削除しますか？")) return;

    target.disabled = true;
    try {
      const response = await fetch("/api/passkeys/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passkey_id: Number(rawPasskeyId) }),
        credentials: "same-origin"
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === "fail") {
        throw new Error(typeof data.error === "string" ? data.error : "Passkeyの削除に失敗しました。");
      }
      await loadPasskeys();
    } catch (error) {
      alert((error as Error).message);
      target.disabled = false;
    }
  });

  return {
    loadPasskeys
  };
}
