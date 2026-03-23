export type SettingsPageElements = {
  changeBtn: HTMLElement | null;
  fileInput: HTMLInputElement | null;
  previewImg: HTMLImageElement | null;
  togglePwd: HTMLElement | null;
  cancelBtn: HTMLElement | null;
  form: HTMLFormElement | null;
  navLinks: NodeListOf<HTMLElement>;
  sections: NodeListOf<HTMLElement>;
  promptListEntriesEl: HTMLElement | null;
  passkeySupportStatusEl: HTMLElement | null;
  passkeyListEl: HTMLElement | null;
  registerPasskeyBtn: HTMLButtonElement | null;
  refreshPasskeysBtn: HTMLButtonElement | null;
};

export function getSettingsPageElements(): SettingsPageElements {
  return {
    changeBtn: document.getElementById("changeAvatarBtn"),
    fileInput: document.getElementById("avatarInput") as HTMLInputElement | null,
    previewImg: document.getElementById("avatarPreview") as HTMLImageElement | null,
    togglePwd: document.getElementById("togglePasswordBtn"),
    cancelBtn: document.getElementById("cancelBtn"),
    form: document.getElementById("userSettingsForm") as HTMLFormElement | null,
    navLinks: document.querySelectorAll<HTMLElement>(".nav-link"),
    sections: document.querySelectorAll<HTMLElement>(".settings-section"),
    promptListEntriesEl: document.getElementById("promptListEntries"),
    passkeySupportStatusEl: document.getElementById("passkeySupportStatus"),
    passkeyListEl: document.getElementById("passkeyList"),
    registerPasskeyBtn: document.getElementById("registerPasskeyBtn") as HTMLButtonElement | null,
    refreshPasskeysBtn: document.getElementById("refreshPasskeysBtn") as HTMLButtonElement | null
  };
}
