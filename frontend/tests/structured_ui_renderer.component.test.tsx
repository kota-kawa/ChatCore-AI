import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StructuredUiRenderer } from "../components/chat_page/structured_ui_renderer";
import { parseStructuredUiV1 } from "../lib/chat_page/structured_ui_contract";
import { clearStructuredUiMetrics, readStructuredUiMetrics, structuredUiMetricsScopeFromStateScope } from "../lib/chat_page/structured_ui_metrics";

const UI = parseStructuredUiV1({
  version: 1,
  id: "answer_form",
  fallback_text: "A form is available in the chat composer.",
  root_id: "root",
  nodes: [
    { id: "root", type: "card", title: "Review", children: ["name", "notes", "enabled", "format", "score", "tabs", "compose", "choice"] },
    { id: "name", type: "input", label: "Name", state_id: "name" },
    { id: "notes", type: "textarea", label: "Notes", state_id: "notes" },
    { id: "enabled", type: "checkbox", label: "Accept terms", state_id: "enabled" },
    { id: "format", type: "select", label: "Format", state_id: "format", options: ["alpha", "beta"] },
    { id: "score", type: "input", label: "Score", state_id: "score", input_type: "number", minimum: 0, maximum: 10, step: 1 },
    { id: "tabs", type: "tabs", title: "Sections", children: ["summary", "details"], labels: ["Summary", "Details"] },
    { id: "summary", type: "text", text: "Summary panel" },
    { id: "details", type: "text", text: "Details panel" },
    { id: "compose", type: "button", label: "Compose", action: { type: "compose", text: "Review this", include_state: ["name"] } },
    { id: "choice", type: "choice", buttons: { type: "yes_no", question: "Proceed?" } },
  ],
  state: [
    { id: "name", initial: "Ada" },
    { id: "notes", initial: "" },
    { id: "enabled", initial: false },
    { id: "format", initial: "alpha" },
    { id: "score", initial: 5 },
  ],
});

if (!UI) throw new Error("Structured UI test fixture is invalid");

const VISUAL_UI = parseStructuredUiV1({
  version: 1,
  id: "visual_gallery",
  fallback_text: "Gallery unavailable",
  root_id: "gallery",
  nodes: [
    { id: "gallery", type: "column", children: ["markdown", "table", "steps", "timeline", "diagram", "line_chart", "bar_chart", "pie_chart", "photo", "flag", "mark_done", "reset_flag", "choice", "divider"] },
    { id: "markdown", type: "markdown", text: "**Safe text** [source](https://source.example) ![remote](https://tracker.example/pixel) <img src=\"https://tracker.example/raw\">" },
    { id: "table", type: "table", caption: "Results", columns: ["Name", "Source"], rows: [["Alpha", "[reference](https://source.example/reference)"]] },
    { id: "steps", type: "steps", title: "Workflow", children: ["step_one", "step_two"], labels: ["One", "Two"] },
    { id: "step_one", type: "text", text: "First step" },
    { id: "step_two", type: "text", text: "Second step" },
    { id: "timeline", type: "timeline", title: "History", children: ["event_one", "event_two"], labels: ["Day one", "Day two"] },
    { id: "event_one", type: "text", text: "Created" },
    { id: "event_two", type: "text", text: "Reviewed" },
    { id: "diagram", type: "diagram", title: "Flow", items: [{ id: "start", label: "Start" }, { id: "finish", label: "Finish" }], edges: [{ source: "start", target: "finish", label: "continue" }] },
    { id: "line_chart", type: "chart", kind: "line", title: "Line", series: [{ label: "Trend", values: [95000, 114788, 154000] }] },
    { id: "bar_chart", type: "chart", kind: "bar", title: "Bars", series: [{ label: "Count", values: [2, 4, 1] }] },
    { id: "pie_chart", type: "chart", kind: "pie", title: "Share", labels: ["A", "B", "C"], series: [{ label: "Share", values: [2, 3, 1] }] },
    { id: "photo", type: "image", ref: 1, alt: "Verified photo" },
    { id: "flag", type: "checkbox", label: "Complete", state_id: "complete" },
    { id: "mark_done", type: "button", label: "Mark complete", action: { type: "set", state_id: "complete", value: { kind: "literal", value: true } } },
    { id: "reset_flag", type: "button", label: "Reset complete", action: { type: "reset", state_id: "complete" } },
    { id: "choice", type: "choice", buttons: { type: "multiple_choice", question: "Choose one", options: ["A", "B"] } },
    { id: "divider", type: "divider" },
  ],
  state: [{ id: "complete", initial: false }],
  images: [{ ref: 1, url: `/api/chat/web-images/${"a".repeat(32)}/token`, source_url: "https://source.example/photo", source_title: "Photo source" }],
});

if (!VISUAL_UI) throw new Error("Structured UI gallery fixture is invalid");

const SOURCE_UI = parseStructuredUiV1({
  version: 1,
  id: "source_summary",
  fallback_text: "Source summary unavailable",
  root_id: "root",
  nodes: [{ id: "root", type: "text", text: "Reference [1]." }],
  sources: [
    { url: "https://example.test/reference", title: "Reference page" },
    { url: "javascript:alert(1)", title: "Unsafe page" },
  ],
});

if (!SOURCE_UI) throw new Error("Structured UI sources fixture is invalid");

const STATE_SCOPE = `${encodeURIComponent("user:42")}:room-7:local%3Aanswer-12:answer_form`;
const STORAGE_KEY = `chatcore.structured-ui:${STATE_SCOPE}`;

describe("StructuredUiRenderer", () => {
  it("renders local controls and persists only checkbox, select, and tab selection", async () => {
    const onCompose = vi.fn();
    const user = userEvent.setup();
    render(<StructuredUiRenderer ui={UI} stateScope={STATE_SCOPE} onCompose={onCompose} />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Grace" } });
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "private note" } });
    const score = screen.getByLabelText("Score");
    await user.clear(score);
    expect(score).toHaveValue("");
    expect(score).toHaveAttribute("aria-invalid", "true");
    await user.type(score, "9");
    expect(score).toHaveValue("9");
    expect(score).toHaveAttribute("aria-invalid", "false");
    fireEvent.click(screen.getByLabelText("Accept terms"));
    fireEvent.change(screen.getByLabelText("Format"), { target: { value: "beta" } });
    fireEvent.click(screen.getByRole("tab", { name: "Details" }));

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as {
      selected: Record<string, unknown>;
      tabs: Record<string, number>;
    };
    expect(stored.selected).toEqual({ enabled: true, format: "beta" });
    expect(stored.tabs).toEqual({ tabs: 1 });
    expect(JSON.stringify(stored)).not.toContain("Grace");
    expect(JSON.stringify(stored)).not.toContain("private note");
    expect(JSON.stringify(stored)).not.toContain("9");
    expect(onCompose).not.toHaveBeenCalled();
  });

  it("restores saved selections and preserves them when a streaming answer id becomes a server id", () => {
    const nextScope = `${encodeURIComponent("user:42")}:room-7:server%3A501:answer_form`;
    const { rerender, unmount } = render(<StructuredUiRenderer ui={UI} stateScope={STATE_SCOPE} />);
    fireEvent.click(screen.getByLabelText("Accept terms"));
    fireEvent.change(screen.getByLabelText("Format"), { target: { value: "beta" } });
    fireEvent.click(screen.getByRole("tab", { name: "Details" }));

    rerender(<StructuredUiRenderer ui={UI} stateScope={nextScope} />);
    expect(screen.getByLabelText("Accept terms")).toBeChecked();
    expect(screen.getByLabelText("Format")).toHaveValue("beta");
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();

    unmount();
    render(<StructuredUiRenderer ui={UI} stateScope={nextScope} />);
    expect(screen.getByLabelText("Accept terms")).toBeChecked();
    expect(screen.getByLabelText("Format")).toHaveValue("beta");
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps selections isolated when another answer reuses the same block id", () => {
    const firstScope = `${encodeURIComponent("user:42")}:room-7:server%3A501:answer_form`;
    const secondScope = `${encodeURIComponent("user:42")}:room-7:server%3A502:answer_form`;
    const { rerender } = render(<StructuredUiRenderer ui={UI} stateScope={firstScope} />);
    fireEvent.click(screen.getByLabelText("Accept terms"));
    fireEvent.change(screen.getByLabelText("Format"), { target: { value: "beta" } });
    fireEvent.click(screen.getByRole("tab", { name: "Details" }));

    rerender(<StructuredUiRenderer ui={UI} stateScope={secondScope} />);
    expect(screen.getByLabelText("Accept terms")).not.toBeChecked();
    expect(screen.getByLabelText("Format")).toHaveValue("alpha");
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");

    rerender(<StructuredUiRenderer ui={UI} stateScope={firstScope} />);
    expect(screen.getByLabelText("Accept terms")).toBeChecked();
    expect(screen.getByLabelText("Format")).toHaveValue("beta");
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps native state local when the scope is omitted", () => {
    render(<StructuredUiRenderer ui={UI} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Local only" } });
    fireEvent.click(screen.getByLabelText("Accept terms"));

    expect(window.localStorage.length).toBe(0);
  });

  it("composes button and standard choice text into the input callback without submitting", () => {
    const onCompose = vi.fn();
    render(<StructuredUiRenderer ui={UI} onCompose={onCompose} />);

    fireEvent.click(screen.getByRole("button", { name: "Compose" }));
    expect(onCompose).toHaveBeenCalledWith("Review this\nname: Ada");
    fireEvent.click(screen.getByRole("button", { name: "はい" }));
    expect(onCompose).toHaveBeenLastCalledWith("Proceed?\nはい");
  });

  it("keeps local controls usable while disabled and blocks draft actions", () => {
    const onCompose = vi.fn();
    render(<StructuredUiRenderer ui={UI} onCompose={onCompose} disabled />);

    expect(screen.getByLabelText("Name")).toBeEnabled();
    expect(screen.getByLabelText("Accept terms")).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Details" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Compose" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "はい" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Accept terms"));
    fireEvent.click(screen.getByRole("tab", { name: "Details" }));
    expect(onCompose).not.toHaveBeenCalled();
  });

  it("records bounded render timing locally without making a request", () => {
    clearStructuredUiMetrics();
    const scope = structuredUiMetricsScopeFromStateScope(STATE_SCOPE);
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    try {
      render(<StructuredUiRenderer ui={UI} stateScope={STATE_SCOPE} />);

      const metric = readStructuredUiMetrics(scope!)?.metrics[0];
      expect(metric?.block_id).toBe("answer_form");
      expect(metric?.render_ms).toBeGreaterThanOrEqual(0);
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
      clearStructuredUiMetrics();
    }
  });

  it("renders the native registry and never loads Markdown HTML or image URLs", () => {
    const { container } = render(<StructuredUiRenderer ui={VISUAL_UI} />);

    expect(screen.getByRole("img", { name: "Line" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Bars" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Share" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("continue")).toBeInTheDocument();
    expect(screen.getByText("Day two")).toBeInTheDocument();
    const yAxisLabel = container.querySelector(".structured-ui__chart-axis text");
    expect(Number(yAxisLabel?.getAttribute("x"))).toBeGreaterThanOrEqual(80);
    expect(screen.getByRole("link", { name: "source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "reference" })).toHaveAttribute("target", "_blank");
    expect(container.querySelectorAll("img")).toHaveLength(1);
    expect(container.querySelector("img")?.getAttribute("src")).toMatch(/^\/api\/chat\/web-images\//);
    expect(container.querySelector("img[src*='tracker.example']")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "次へ" }));
    expect(screen.getByText("Second step")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    expect(screen.getByLabelText("Complete")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Reset complete" }));
    expect(screen.getByLabelText("Complete")).not.toBeChecked();
  });

  it("keeps DOM ids unique across UI instances and renders numbered safe sources last", () => {
    const { container } = render(<>
      <StructuredUiRenderer key="form-one" ui={UI} />
      <StructuredUiRenderer key="form-two" ui={UI} />
      <StructuredUiRenderer key="gallery-one" ui={VISUAL_UI} />
      <StructuredUiRenderer key="gallery-two" ui={VISUAL_UI} />
      <StructuredUiRenderer key="sources" ui={SOURCE_UI} />
    </>);

    const ids = Array.from(container.querySelectorAll<HTMLElement>("[id]"), (element) => element.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);

    for (const tab of container.querySelectorAll<HTMLElement>("[role='tab']")) {
      expect(document.getElementById(tab.getAttribute("aria-controls") ?? "")).not.toBeNull();
    }
    for (const chart of container.querySelectorAll<SVGElement>("svg[aria-labelledby]")) {
      expect(document.getElementById(chart.getAttribute("aria-labelledby") ?? "")).not.toBeNull();
    }

    const sourceSection = container.querySelector(".structured-ui__sources");
    expect(sourceSection).not.toBeNull();
    expect(sourceSection?.parentElement?.lastElementChild).toBe(sourceSection);
    expect(sourceSection?.querySelector("ol li a")).toHaveAttribute("href", "https://example.test/reference");
    expect(sourceSection?.querySelector("ol li a")).toHaveAttribute("target", "_blank");
    expect(sourceSection?.querySelector("ol li a")).toHaveAttribute("rel", "noopener noreferrer");
    expect(sourceSection?.querySelectorAll("li")).toHaveLength(1);
    expect(screen.getByText("Reference [1].")).toBeInTheDocument();
  });

  it("shows a local error and does not compose while a numeric field is invalid", async () => {
    const user = userEvent.setup();
    const onCompose = vi.fn();
    render(<StructuredUiRenderer ui={UI} onCompose={onCompose} />);

    await user.clear(screen.getByLabelText("Score"));
    await user.click(screen.getByRole("button", { name: "Compose" }));

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(onCompose).not.toHaveBeenCalled();
  });
});
