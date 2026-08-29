import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../contexts/locale_context";
import { SkillSection } from "../components/chat_page/skill_section";
import type { UserSkill } from "../lib/chat_page/skill_api";
import { useHomePageSkills } from "../hooks/chat_page/use_home_page_skills";

vi.mock("../hooks/chat_page/use_home_page_skills", () => ({
  useHomePageSkills: vi.fn(),
}));

const skill: UserSkill = {
  id: 1,
  name: "短く答える",
  instructions: "結論から書く",
  is_enabled: true,
  system_skill_key: null,
  is_default: false,
  can_edit: true,
  can_delete: true,
  created_at: null,
  updated_at: null,
};

const mockedUseHomePageSkills = vi.mocked(useHomePageSkills);

function renderSection() {
  return render(
    <LocaleProvider initialLocale="ja">
      <SkillSection loggedIn />
    </LocaleProvider>,
  );
}

function state(overrides: Partial<ReturnType<typeof useHomePageSkills>> = {}) {
  return {
    skills: [skill],
    error: undefined,
    isLoading: false,
    isAddModalOpen: false,
    skillName: "",
    skillInstructions: "",
    isSaving: false,
    pendingSkillId: null,
    openAddModal: vi.fn(),
    closeAddModal: vi.fn(),
    setSkillName: vi.fn(),
    setSkillInstructions: vi.fn(),
    handleCreate: vi.fn(),
    handleToggle: vi.fn(),
    handleDelete: vi.fn(),
    retry: vi.fn(),
    ...overrides,
  };
}

describe("SkillSection", () => {
  beforeEach(() => {
    mockedUseHomePageSkills.mockReset();
  });

  it("does not render personal skills for guests", () => {
    mockedUseHomePageSkills.mockReturnValue(state());
    render(
      <LocaleProvider initialLocale="ja">
        <SkillSection loggedIn={false} />
      </LocaleProvider>,
    );
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("renders an accessible switch and delegates toggles", () => {
    const handleToggle = vi.fn();
    mockedUseHomePageSkills.mockReturnValue(state({ handleToggle }));
    renderSection();

    const toggle = screen.getByRole("switch", { name: /短く答えるをオフ/ });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    expect(handleToggle).toHaveBeenCalledWith(skill);
  });

  it("opens the full Skill instructions from the chip body", () => {
    mockedUseHomePageSkills.mockReturnValue(state());
    renderSection();

    fireEvent.click(screen.getByRole("button", { name: "短く答えるの内容を表示" }));

    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByRole("heading", { name: "短く答える" })).toBeInTheDocument();
    expect(screen.getByText("結論から書く")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "モーダルを閉じる" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the add flow from the empty state", () => {
    const openAddModal = vi.fn();
    mockedUseHomePageSkills.mockReturnValue(state({ skills: [], openAddModal }));
    renderSection();

    fireEvent.click(screen.getByRole("button", { name: /最初のSkillを追加/ }));
    expect(openAddModal).toHaveBeenCalledOnce();
  });

  it("marks the default Skill and does not expose delete", () => {
    mockedUseHomePageSkills.mockReturnValue(state({
      skills: [{
        ...skill,
        id: 0,
        name: "生成UI",
        system_skill_key: "generative_ui",
        is_default: true,
        can_edit: false,
        can_delete: false,
      }],
    }));
    renderSection();

    expect(screen.getByText("デフォルト")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成UIを削除" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /生成UIをオフ/ })).toBeInTheDocument();
  });
});
