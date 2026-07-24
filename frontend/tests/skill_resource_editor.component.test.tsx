import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { SkillResourceEditor } from "../components/prompt_share/skill_resource_editor";
import type { PromptResource } from "../scripts/prompt_share/types";

function SkillResourceEditorHarness() {
  const [resources, setResources] = useState<PromptResource[]>([]);
  return (
    <SkillResourceEditor
      resources={resources}
      setResources={setResources}
      onEdit={vi.fn()}
    />
  );
}

describe("SkillResourceEditor", () => {
  it("adds, infers, edits, and removes a named resource", () => {
    render(<SkillResourceEditorHarness />);

    expect(screen.getByText(/追加リソースはありません/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "リソースを追加" }));

    fireEvent.change(screen.getByLabelText("ファイルパス"), {
      target: { value: "scripts/run.ts" }
    });
    expect(screen.getByLabelText("言語")).toHaveValue("typescript");

    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "export const run = () => true;" }
    });
    expect(screen.getByDisplayValue("export const run = () => true;")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "リソース 1 を削除" }));
    expect(screen.getByText(/追加リソースはありません/)).toBeInTheDocument();
  });
});
