// 開いたメニューの外を押したとき、閉じるだけで押した先には何も起きないことを検証する。
// Tests that a press outside an open menu only closes it and never reaches what was pressed.

import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useDismissOnOutsidePress } from "../hooks/use_dismiss_on_outside_press";

function Menu({ label, onDismiss }: { label: string; onDismiss?: () => void }) {
  const [open, setOpen] = useState(true);
  const ref = useRef<HTMLDivElement | null>(null);
  useDismissOnOutsidePress(open, (target) => Boolean(ref.current?.contains(target)), () => {
    onDismiss?.();
    setOpen(false);
  });
  return (
    <div ref={ref}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((previous) => !previous)}>{label}</button>
      {open && <button type="button">{`${label} item`}</button>}
    </div>
  );
}

// 実ブラウザのマウス操作と同じ順に、押してから離すまでのイベントを送る
// Dispatch a whole mouse press in the order a real browser does
function pressWithMouse(element: Element) {
  const pointerDown = fireEvent.pointerDown(element);
  const mouseDown = fireEvent.mouseDown(element);
  fireEvent.pointerUp(element);
  fireEvent.mouseUp(element);
  const click = fireEvent.click(element, { detail: 1 });
  return { pointerDown, mouseDown, click };
}

describe("useDismissOnOutsidePress", () => {
  // メモ本文を押したら閉じるだけにし、カーソル移動もボタンの反応も起こさない。
  // Pressing the memo body only closes the menu: no caret move, no button reaction.
  it("closes on an outside press and swallows the rest of that press", () => {
    const onOutsideClick = vi.fn();
    const onOutsideMouseDown = vi.fn();
    render(
      <>
        <Menu label="menu" />
        <button type="button" onClick={onOutsideClick} onMouseDown={onOutsideMouseDown}>outside</button>
      </>,
    );
    const outside = screen.getByRole("button", { name: "outside" });

    const { mouseDown, click } = pressWithMouse(outside);

    expect(screen.getByRole("button", { name: "menu" })).toHaveAttribute("aria-expanded", "false");
    // fireEvent は既定動作が打ち消されたとき false を返す / fireEvent returns false when the default was prevented
    expect(mouseDown).toBe(false);
    expect(click).toBe(false);
    expect(onOutsideMouseDown).not.toHaveBeenCalled();
    expect(onOutsideClick).not.toHaveBeenCalled();
  });

  it("leaves presses inside the menu alone", () => {
    render(<Menu label="menu" />);
    const item = screen.getByRole("button", { name: "menu item" });

    const { mouseDown } = pressWithMouse(item);

    expect(mouseDown).toBe(true);
    expect(screen.getByRole("button", { name: "menu" })).toHaveAttribute("aria-expanded", "true");
  });

  // ほかのメニューの開くボタンも外側なので、1 回目は閉じるだけで、相手のメニューは開かない。
  // Another menu's trigger is outside too, so the first press only closes and does not open that menu.
  it("treats another menu's trigger as outside", () => {
    function Pair() {
      const [secondOpen, setSecondOpen] = useState(false);
      return (
        <>
          <Menu label="first" />
          <button type="button" aria-expanded={secondOpen} onClick={() => setSecondOpen(true)}>second</button>
        </>
      );
    }
    render(<Pair />);
    const second = screen.getByRole("button", { name: "second" });

    pressWithMouse(second);
    expect(screen.getByRole("button", { name: "first" })).toHaveAttribute("aria-expanded", "false");
    expect(second).toHaveAttribute("aria-expanded", "false");

    pressWithMouse(second);
    expect(second).toHaveAttribute("aria-expanded", "true");
  });

  // 入れ子で開いたメニューは、外側の 1 回の押下でどちらも閉じる。
  // Menus open at the same time all close on one outside press.
  it("closes every open menu on one outside press", () => {
    const onFirstDismiss = vi.fn();
    const onSecondDismiss = vi.fn();
    render(
      <>
        <Menu label="first" onDismiss={onFirstDismiss} />
        <Menu label="second" onDismiss={onSecondDismiss} />
        <button type="button">outside</button>
      </>,
    );

    pressWithMouse(screen.getByRole("button", { name: "outside" }));

    expect(onFirstDismiss).toHaveBeenCalledTimes(1);
    expect(onSecondDismiss).toHaveBeenCalledTimes(1);
  });

  // 押下の終わりを受け取れなくても、次のキー操作による click は打ち消さない。
  // Even when the end of the press is never seen, a later keyboard click still goes through.
  it("never swallows a keyboard click after the press", () => {
    const onOutsideClick = vi.fn();
    render(
      <>
        <Menu label="menu" />
        <button type="button" onClick={onOutsideClick}>outside</button>
      </>,
    );
    const outside = screen.getByRole("button", { name: "outside" });

    fireEvent.pointerDown(outside);
    fireEvent.keyDown(outside, { key: "Enter" });
    fireEvent.click(outside);

    expect(onOutsideClick).toHaveBeenCalledTimes(1);
  });
});
