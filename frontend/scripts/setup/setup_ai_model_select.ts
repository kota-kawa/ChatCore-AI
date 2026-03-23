export function initAiModelSelect() {
  const nativeSelect = document.getElementById("ai-model") as HTMLSelectElement | null;
  if (!nativeSelect) return;
  if (nativeSelect.dataset.modernSelectInitialized === "true") return;

  nativeSelect.dataset.modernSelectInitialized = "true";
  nativeSelect.classList.add("model-select-native");

  const wrapper = document.createElement("div");
  wrapper.className = "model-select";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "model-select-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");

  const menu = document.createElement("div");
  menu.className = "model-select-menu";
  menu.setAttribute("role", "listbox");

  const closeMenu = () => {
    wrapper.classList.remove("is-open");
    trigger.setAttribute("aria-expanded", "false");
  };

  const openMenu = () => {
    wrapper.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  };

  const syncFromSelect = () => {
    const selected = nativeSelect.options[nativeSelect.selectedIndex];
    trigger.textContent = selected?.textContent?.trim() || "";

    menu.querySelectorAll<HTMLButtonElement>(".model-select-option").forEach((optionButton) => {
      const isSelected = optionButton.dataset.value === nativeSelect.value;
      optionButton.classList.toggle("is-selected", isSelected);
      optionButton.setAttribute("aria-selected", isSelected ? "true" : "false");
    });
  };

  [...nativeSelect.options].forEach((option) => {
    const optionButton = document.createElement("button");
    optionButton.type = "button";
    optionButton.className = "model-select-option";
    optionButton.setAttribute("role", "option");
    optionButton.dataset.value = option.value;
    optionButton.textContent = option.textContent || option.value;

    optionButton.addEventListener("click", (e) => {
      e.preventDefault();
      if (nativeSelect.value !== option.value) {
        nativeSelect.value = option.value;
        nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
      closeMenu();
    });

    menu.appendChild(optionButton);
  });

  trigger.addEventListener("click", (e) => {
    e.preventDefault();
    if (wrapper.classList.contains("is-open")) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  trigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openMenu();
    }
    if (e.key === "Escape") {
      closeMenu();
    }
  });

  document.addEventListener("click", (e) => {
    const target = e.target as Node | null;
    if (!target) return;
    if (!wrapper.contains(target)) {
      closeMenu();
    }
  });

  nativeSelect.addEventListener("change", syncFromSelect);

  wrapper.append(trigger, menu);
  nativeSelect.insertAdjacentElement("afterend", wrapper);
  syncFromSelect();
}
