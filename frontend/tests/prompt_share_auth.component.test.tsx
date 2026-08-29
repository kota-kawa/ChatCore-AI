import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePromptShareAuth } from "../components/prompt_share/use_prompt_share_auth";

const mocks = vi.hoisted(() => ({
  resilientFetch: vi.fn()
}));

vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: mocks.resilientFetch
}));

function AuthHarness() {
  const { authUiReady, currentUserId, isLoggedIn } = usePromptShareAuth();
  return (
    <output>
      {authUiReady ? "ready" : "loading"}:{isLoggedIn ? "in" : "out"}:{currentUserId ?? "none"}
    </output>
  );
}

describe("usePromptShareAuth", () => {
  beforeEach(() => {
    mocks.resilientFetch.mockResolvedValue(new Response(JSON.stringify({
      logged_in: true,
      user: { id: 42 }
    }), {
      status: 200,
      headers: { "content-type": "application/json" }
    }));
  });

  it("現在ユーザーIDを認証レスポンスから保持する", async () => {
    render(<AuthHarness />);

    await waitFor(() => {
      expect(screen.getByText("ready:in:42")).toBeInTheDocument();
    });
  });
});
