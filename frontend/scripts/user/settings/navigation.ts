type NavigationModuleOptions = {
  navLinks: NodeListOf<HTMLElement>;
  sections: NodeListOf<HTMLElement>;
  onPromptsSection: () => void;
  onPromptListSection: () => void;
  onSecuritySection: () => void;
};

export function setupSettingsNavigation(options: NavigationModuleOptions) {
  const { navLinks, sections, onPromptsSection, onPromptListSection, onSecuritySection } = options;

  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();

      navLinks.forEach((l) => l.classList.remove("active"));
      link.classList.add("active");

      const targetSection = link.dataset.section;
      if (!targetSection) return;
      sections.forEach((section) => {
        if (section.id === `${targetSection}-section`) {
          section.classList.add("active");
        } else {
          section.classList.remove("active");
        }
      });

      if (targetSection === "prompts") {
        onPromptsSection();
      } else if (targetSection === "prompt-list") {
        onPromptListSection();
      } else if (targetSection === "security") {
        onSecuritySection();
      }
    });
  });
}
