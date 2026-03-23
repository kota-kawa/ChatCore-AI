export type ProfileModuleOptions = {
  changeBtn: HTMLElement | null;
  fileInput: HTMLInputElement | null;
  previewImg: HTMLImageElement | null;
  togglePwd: HTMLElement | null;
  cancelBtn: HTMLElement | null;
  form: HTMLFormElement | null;
};

export function setupProfileModule(options: ProfileModuleOptions) {
  const { changeBtn, fileInput, previewImg, togglePwd, cancelBtn, form } = options;

  changeBtn?.addEventListener("click", () => fileInput?.click());
  fileInput?.addEventListener("change", (e) => {
    const target = e.target as HTMLInputElement | null;
    const file = target?.files?.[0];
    if (file && file.type.startsWith("image/") && previewImg) {
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result === "string") previewImg.src = reader.result;
      };
      reader.readAsDataURL(file);
    }
  });

  togglePwd?.addEventListener("click", () => {
    const pwd = document.getElementById("password") as HTMLInputElement | null;
    if (!pwd) return;
    const isPwd = pwd.type === "password";
    pwd.type = isPwd ? "text" : "password";
    togglePwd.innerHTML = isPwd
      ? '<i class="bi bi-eye-slash"></i>'
      : '<i class="bi bi-eye"></i>';
  });

  cancelBtn?.addEventListener("click", () => {
    form?.reset();
    if (previewImg) previewImg.src = "/static/user-icon.png";
    if (togglePwd) togglePwd.innerHTML = '<i class="bi bi-eye"></i>';
  });

  async function loadProfile() {
    try {
      const res = await fetch("/api/user/profile", { credentials: "same-origin" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "取得失敗");

      const usernameEl = document.getElementById("username") as HTMLInputElement | null;
      const emailEl = document.getElementById("email") as HTMLInputElement | null;
      const bioEl = document.getElementById("bio") as HTMLTextAreaElement | null;
      if (usernameEl) usernameEl.value = data.username ?? "";
      if (emailEl) emailEl.value = data.email ?? "";
      if (bioEl) bioEl.value = data.bio ?? "";
      if (data.avatar_url && previewImg) previewImg.src = data.avatar_url;
    } catch (err) {
      console.error("loadProfile:", (err as Error).message);
    }
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const usernameEl = document.getElementById("username") as HTMLInputElement | null;
    const emailEl = document.getElementById("email") as HTMLInputElement | null;
    const bioEl = document.getElementById("bio") as HTMLTextAreaElement | null;
    if (!usernameEl || !emailEl || !bioEl) {
      alert("フォーム要素が見つかりませんでした。");
      return;
    }

    const fd = new FormData();
    fd.append("username", usernameEl.value.trim());
    fd.append("email", emailEl.value.trim());
    fd.append("bio", bioEl.value.trim());
    if (fileInput?.files && fileInput.files.length > 0) fd.append("avatar", fileInput.files[0]);

    try {
      const res = await fetch("/api/user/profile", {
        method: "POST",
        body: fd,
        credentials: "same-origin"
      });
      const ctype = res.headers.get("Content-Type") || "";
      const body = ctype.includes("application/json")
        ? await res.json()
        : { error: await res.text() };

      if (!res.ok) throw new Error(body.error || "更新失敗");
      alert(body.message || "プロフィールを更新しました");
      if (body.avatar_url && previewImg) previewImg.src = body.avatar_url;
    } catch (err) {
      alert("エラー: " + (err as Error).message);
    }
  });

  return {
    loadProfile
  };
}
