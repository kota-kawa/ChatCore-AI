import { getSettingsPageElements } from "./settings/dom";
import { setupSettingsNavigation } from "./settings/navigation";
import { setupPasskeyModule } from "./settings/passkeys";
import { setupProfileModule } from "./settings/profile";
import { setupPromptListModule } from "./settings/prompt_list";
import { setupPromptManageModule } from "./settings/prompt_manage";

const initSettingsPage = () => {
  const elements = getSettingsPageElements();

  const profileModule = setupProfileModule({
    changeBtn: elements.changeBtn,
    fileInput: elements.fileInput,
    previewImg: elements.previewImg,
    togglePwd: elements.togglePwd,
    cancelBtn: elements.cancelBtn,
    form: elements.form
  });

  const passkeyModule = setupPasskeyModule({
    passkeySupportStatusEl: elements.passkeySupportStatusEl,
    passkeyListEl: elements.passkeyListEl,
    registerPasskeyBtn: elements.registerPasskeyBtn,
    refreshPasskeysBtn: elements.refreshPasskeysBtn
  });

  const promptManageModule = setupPromptManageModule();

  const promptListModule = setupPromptListModule({
    promptListEntriesEl: elements.promptListEntriesEl
  });

  setupSettingsNavigation({
    navLinks: elements.navLinks,
    sections: elements.sections,
    onPromptsSection: () => {
      promptManageModule.loadMyPrompts();
    },
    onPromptListSection: () => {
      promptListModule.loadPromptList();
    },
    onSecuritySection: () => {
      void passkeyModule.loadPasskeys();
    }
  });

  profileModule.loadProfile();
  void passkeyModule.loadPasskeys();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSettingsPage);
} else {
  initSettingsPage();
}

export {};
