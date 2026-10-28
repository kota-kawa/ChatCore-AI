import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

import { DemoCodesPanel } from "../components/admin/demo_codes_panel";
import { LocaleProvider } from "../contexts/locale_context";
import { resilientFetch } from "../scripts/core/resilient_fetch";
import type { DemoAccessCodeApi } from "../types/generated/api_schemas";

const fetchMock = vi.mocked(resilientFetch);

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

function codeItem(overrides: Partial<DemoAccessCodeApi>): DemoAccessCodeApi {
  return {
    id: 1,
    label: "Acme",
    status: "unused",
    created_at: "2026-10-01T00:00:00+09:00",
    first_used_at: null,
    expires_at: null,
    used_usd: null,
    limit_usd: 1.5,
    ...overrides,
  };
}

const ACTIVE = codeItem({
  id: 4,
  label: "サンプル株式会社",
  status: "active",
  first_used_at: "2026-10-25T10:00:00+09:00",
  expires_at: "2026-11-24T10:00:00+09:00",
  used_usd: 0.12,
});
const UNUSED = codeItem({ id: 3, label: "Acme" });
const ENDED = codeItem({ id: 2, label: "Globex", status: "ended", first_used_at: "2026-09-01T00:00:00+09:00", expires_at: "2026-10-01T00:00:00+09:00" });
const REVOKED = codeItem({ id: 1, label: "Initech", status: "revoked" });

function renderPanel(onUnauthorized = vi.fn()) {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <LocaleProvider initialLocale="ja">
        <DemoCodesPanel onUnauthorized={onUnauthorized} />
      </LocaleProvider>
    </SWRConfig>
  );
  return onUnauthorized;
}

const callsTo = (fragment: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(fragment));

describe("DemoCodesPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("lists codes with status, dates and spend, and offers 停止 only for unused and active codes", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ codes: [ACTIVE, UNUSED, ENDED, REVOKED] }));
    renderPanel();

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("利用中")).toBeInTheDocument();
    expect(within(rows[0]).getByText("$0.12 / $1.50")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026/11/24")).toBeInTheDocument();
    expect(within(rows[1]).getByText("未使用")).toBeInTheDocument();
    expect(within(rows[2]).getByText("終了")).toBeInTheDocument();
    expect(within(rows[3]).getByText("停止")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "「サンプル株式会社」のコードを停止" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "「Acme」のコードを停止" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "「Globex」のコードを停止" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "「Initech」のコードを停止" })).not.toBeInTheDocument();
  });

  it("issues a code, shows it once with a copy button, and refreshes the list", async () => {
    let issued = false;
    fetchMock.mockImplementation(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "POST") {
        issued = true;
        return jsonResponse({ code: "demo-ab3k-x9qa-7mpz", item: UNUSED }, 201);
      }
      return jsonResponse({ codes: issued ? [UNUSED] : [] });
    });
    renderPanel();
    expect(await screen.findByText("まだコードを発行していません。")).toBeInTheDocument();

    const user = userEvent.setup();
    const issueButton = screen.getByRole("button", { name: "発行" });
    expect(issueButton).toBeDisabled();
    await user.type(screen.getByLabelText("応募先・宛先の名前"), "  Acme ");
    await user.click(issueButton);

    expect(await screen.findByText("demo-ab3k-x9qa-7mpz")).toBeInTheDocument();
    expect(screen.getByText(/今しか表示されません/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "コードをコピー" })).toBeInTheDocument();
    const [[, init]] = callsTo("/admin/api/demo-codes").filter(([, requestInit]) => requestInit?.method === "POST");
    expect(JSON.parse(String(init?.body))).toEqual({ label: "Acme" });
    expect(await within(await screen.findByRole("table")).findByText("未使用")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "閉じる" }));
    expect(screen.queryByText("demo-ab3k-x9qa-7mpz")).not.toBeInTheDocument();
  });

  it("shows the server's message when issuing fails", async () => {
    fetchMock.mockImplementation(async (_url: unknown, init?: RequestInit) =>
      init?.method === "POST" ? jsonResponse({ status: "fail", error: "ラベルが長すぎます" }, 400) : jsonResponse({ codes: [] })
    );
    renderPanel();
    await screen.findByText("まだコードを発行していません。");

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("応募先・宛先の名前"), "x");
    await user.click(screen.getByRole("button", { name: "発行" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("ラベルが長すぎます");
  });

  it("asks for confirmation before stopping a code and only then calls the API", async () => {
    let revoked = false;
    fetchMock.mockImplementation(async (url: unknown) => {
      if (String(url).endsWith("/4/revoke")) {
        revoked = true;
        return jsonResponse({ item: { ...ACTIVE, status: "revoked", used_usd: null } });
      }
      return jsonResponse({ codes: [revoked ? { ...ACTIVE, status: "revoked", used_usd: null } : ACTIVE] });
    });
    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "「サンプル株式会社」のコードを停止" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/元に戻せません/)).toBeInTheDocument();
    expect(callsTo("/revoke")).toHaveLength(0);

    // キャンセルすると何も送らず閉じる / Cancelling closes without any request
    await user.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(callsTo("/revoke")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "「サンプル株式会社」のコードを停止" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "停止する" }));

    await waitFor(() => expect(callsTo("/4/revoke")).toHaveLength(1));
    expect(callsTo("/4/revoke")[0][1]?.method).toBe("POST");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("button", { name: /のコードを停止/ })).not.toBeInTheDocument());
  });

  it("sends the admin back to the login page when the session has expired", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "fail", error: "Unauthorized" }, 401));
    const onUnauthorized = renderPanel();

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
    expect(screen.queryByText("Unauthorized")).not.toBeInTheDocument();
  });
});
