import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const { useController, translate, useTranslation, renderSeo } = vi.hoisted(() => {
  const translate = (key: string) => key;
  return {
    useController: vi.fn(),
    translate,
    useTranslation: vi.fn(() => ({ locale: "ja", t: translate })),
    renderSeo: vi.fn((_props: { title: string }) => null),
  };
});

vi.mock("../hooks/chat_page/use_home_page_controller", () => ({ useHomePageController: useController }));
vi.mock("../contexts/locale_context", () => ({ useTranslation }));
vi.mock("../components/SeoHead", () => ({ SeoHead: renderSeo }));
vi.mock("../components/chat_page/setup_section", () => ({ SetupSection: () => null }));
vi.mock("../components/chat_page/chat_main_section", () => ({ ChatMainSection: () => null }));
vi.mock("../contexts/chat_page/home_page_context", () => ({
  HomePageContextProvider: ({ children }: { children: ReactNode }) => children,
  useHomePageProjectContext: () => ({ activeProjectDetail: null, activeProjectId: null, isProjectModalOpen: false }),
  useHomePageChatContext: () => ({}),
}));

import HomePage from "../pages/index";

type Controller = ReturnType<typeof import("../hooks/chat_page/use_home_page_controller").useHomePageController>;

function makeController() {
  return {
    loggedIn: true,
    authDisplayReady: true,
    pageViewState: "setup",
    isNewPromptModalOpen: false,
    closeNewPromptModal: vi.fn(),
    setTaskDetail: vi.fn(),
    taskDetail: null,
    isPromptSubmitting: false,
    guardrailEnabled: false,
    newPromptTitle: "",
    newPromptContent: "",
    newPromptInputExample: "",
    newPromptOutputExample: "",
    newPromptStatus: { message: "", variant: "info" },
    titleInputRef: { current: null },
    contentInputRef: { current: null },
    inputExampleRef: { current: null },
    outputExampleRef: { current: null },
    newPromptAssistRootRef: { current: null },
    handlePromptSubmit: vi.fn(),
    setGuardrailEnabled: vi.fn(),
    setNewPromptTitle: vi.fn(),
    setNewPromptContent: vi.fn(),
    setNewPromptInputExample: vi.fn(),
    setNewPromptOutputExample: vi.fn(),
    taskEditModalOpen: false,
    taskEditForm: { name: "", prompt_template: "", response_rules: "", output_skeleton: "", input_examples: "", output_examples: "" },
    closeTaskEditModal: vi.fn(),
    setTaskEditForm: vi.fn(),
    handleTaskEditSave: vi.fn(),
    shareModalOpen: false,
    shareStatus: { message: "", error: false },
    shareUrl: "",
    shareLoading: false,
    supportsNativeShare: false,
    shareXUrl: "",
    shareLineUrl: "",
    shareFacebookUrl: "",
    closeShareModal: vi.fn(),
    copyShareLink: vi.fn(),
    shareWithNativeSheet: vi.fn(),
  } as unknown as Controller;
}

describe("home page rendering", () => {
  beforeEach(() => {
    useTranslation.mockReturnValue({ locale: "ja", t: translate });
  });

  it("keeps closed modal trees and SEO stable when only setup input changes", async () => {
    const controller = makeController();
    useController.mockReturnValue(controller);
    const view = render(<HomePage />);
    await waitFor(() => expect(document.getElementById("newPromptModal")).not.toBeNull());
    const translationsBefore = useTranslation.mock.calls.length;
    const seoBefore = renderSeo.mock.calls.length;

    for (const setupInfo of ["a", "ab", "abc"]) {
      useController.mockReturnValue({ ...controller, setupInfo });
      view.rerender(<HomePage />);
    }

    // The page still renders each keystroke; modal-local translation hooks do not.
    expect(useTranslation.mock.calls.length - translationsBefore).toBe(3);
    expect(renderSeo.mock.calls.length).toBe(seoBefore);
  });

  it("updates open forms and uses the latest submit handler", async () => {
    const controller = makeController();
    useController.mockReturnValue(controller);
    const view = render(<HomePage />);
    await waitFor(() => expect(document.getElementById("newPromptModal")).not.toBeNull());
    const submit = vi.fn();
    useController.mockReturnValue({ ...controller, isNewPromptModalOpen: true, newPromptTitle: "Current title", handlePromptSubmit: submit });
    view.rerender(<HomePage />);

    const title = document.getElementById("new-prompt-title") as HTMLInputElement;
    expect(title.value).toBe("Current title");
    fireEvent.change(title, { target: { value: "Edited title" } });
    expect(controller.setNewPromptTitle).toHaveBeenCalledWith("Edited title");
    fireEvent.submit(document.getElementById("newPostForm")!);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(controller.handlePromptSubmit).not.toHaveBeenCalled();
    fireEvent.click(document.getElementById("newModalCloseBtn")!);
    expect(controller.closeNewPromptModal).toHaveBeenCalledTimes(1);
  });

  it("refreshes SEO when the locale changes", () => {
    useController.mockReturnValue(makeController());
    const view = render(<HomePage />);
    const english = (key: string) => `English ${key}`;
    useTranslation.mockReturnValue({ locale: "en", t: english });
    view.rerender(<HomePage />);
    expect(renderSeo.mock.lastCall?.[0]).toMatchObject({ title: "English home.seoTitle" });
  });
});
