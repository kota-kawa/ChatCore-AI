import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContentImportButton } from "../components/ui/content_import_button";

describe("ContentImportButton", () => {
  it("renders the labelled pending state and prevents clicks while pending", () => {
    const onClick = vi.fn();
    render(
      <ContentImportButton
        variant="labelled"
        label="Continue"
        pendingLabel="Preparing"
        pending={true}
        iconClass="bi-chat-dots"
        onClick={onClick}
      />,
    );

    const button = screen.getByRole("button", { name: "Preparing" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button.querySelector("i")).toHaveClass("bi-arrow-repeat");
    expect(button.querySelector("span")).toHaveTextContent("Preparing");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("supports compact active state without rendering a visible label", () => {
    render(
      <ContentImportButton
        variant="compact"
        label="Added"
        pending={false}
        active={true}
        disableWhenActive={true}
        ariaPressed={true}
        iconClass="bi-plus-square-fill"
        onClick={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Added" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button.querySelector("span")).toBeNull();
  });
});
