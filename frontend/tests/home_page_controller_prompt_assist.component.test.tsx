import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";
import { NewPromptModal } from "../components/chat_page/modals/new_prompt_modal";
import { initPromptAssist } from "../scripts/components/prompt_assist";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/toast", () => ({ showToast: vi.fn() }));
vi.mock("../scripts/components/prompt_assist", () => ({ initPromptAssist: vi.fn(() => ({ destroy: vi.fn() })) }));
vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

const fetchMock = vi.mocked(resilientFetch);
const initPromptAssistMock = vi.mocked(initPromptAssist);

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as unknown as Response;
}

function installMatchMediaStub() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }),
  });
}

// ModalShell はマウント後の自身の useEffect(() => setMounted(true), []) が
// コミットされるまで null を返す。task modal のAI補助を初期化する effect が
// 依存配列 [] のままだと、その最初のコミット時点で ref が全て null のまま
// 空振りし、以後モーダルを開いても二度と初期化されない。
// ModalShell returns null until its own useEffect(() => setMounted(true), [])
// commits. If the task modal's AI-assist init effect keeps an empty
// dependency array, it no-ops on that first commit (all refs are still null)
// and never gets another chance to initialize once the modal opens.
describe("new prompt modal AI assist initialization", () => {
  it("initializes prompt assist once the modal actually opens", async () => {
    installMatchMediaStub();
    localStorage.clear();
    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return jsonResponse({ logged_in: true, user: { id: 7 } });
      return jsonResponse({});
    });

    let controller: ReturnType<typeof useHomePageController> | null = null;
    function Harness() {
      controller = useHomePageController();
      return (
        <NewPromptModal
          isOpen={controller.isNewPromptModalOpen}
          isPromptSubmitting={false}
          guardrailEnabled={false}
          newPromptTitle=""
          newPromptContent=""
          newPromptInputExample=""
          newPromptOutputExample=""
          newPromptStatus={controller.newPromptStatus}
          titleInputRef={controller.titleInputRef}
          contentInputRef={controller.contentInputRef}
          inputExampleRef={controller.inputExampleRef}
          outputExampleRef={controller.outputExampleRef}
          newPromptAssistRootRef={controller.newPromptAssistRootRef}
          onClose={controller.closeNewPromptModal}
          onSubmit={() => {}}
          setGuardrailEnabled={controller.setGuardrailEnabled}
          setNewPromptTitle={controller.setNewPromptTitle}
          setNewPromptContent={controller.setNewPromptContent}
          setNewPromptInputExample={controller.setNewPromptInputExample}
          setNewPromptOutputExample={controller.setNewPromptOutputExample}
        />
      );
    }

    await act(async () => {
      render(<Harness />);
    });
    // モーダルが閉じている間は refs が null のままなので、初期化されなくて正しい。
    // While the modal is closed the refs stay null, so no init is expected yet.
    expect(initPromptAssistMock).not.toHaveBeenCalled();

    await act(async () => {
      controller!.openNewPromptModal();
    });

    expect(initPromptAssistMock).toHaveBeenCalledTimes(1);
  });
});
