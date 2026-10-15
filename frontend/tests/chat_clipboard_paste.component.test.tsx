import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatClipboardPaste } from "../hooks/chat_page/use_chat_clipboard_paste";
import { useChatAttachmentDropzone } from "../hooks/chat_page/use_chat_attachment_dropzone";
import type { AttachedFile } from "../lib/chat_page/types";
import { downscaleChatImage } from "../lib/chat_page/chat_images";

vi.mock("../lib/chat_page/chat_images", async (importOriginal) => ({
  ...await importOriginal<typeof import("../lib/chat_page/chat_images")>(),
  downscaleChatImage: vi.fn(async () => ({ dataBase64: "aW1hZ2U=", mediaType: "image/webp", size: 5 })),
}));

const notifyError = vi.fn();
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
afterEach(() => {
  if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
  else Reflect.deleteProperty(navigator, "clipboard");
});

function setClipboard(value: object | undefined) {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}

function textItem(text: string) {
  return { types: ["text/plain"], getType: vi.fn(async () => ({ text: async () => text })) };
}

function imageItem() {
  return {
    types: ["image/png", "text/plain"],
    getType: vi.fn(async () => new Blob(["image"], { type: "image/png" })),
  };
}

function Harness({ disabled = false, allowImages = true, scopeKey = "room-a", full = false } = {}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("前後");
  const [files, setFiles] = useState<AttachedFile[]>(full
    ? Array.from({ length: 5 }, (_, index) => ({ id: String(index), name: `${index}.txt`, size: 1, content: "x" }))
    : []);
  const { attachSelectedFiles } = useChatAttachmentDropzone({
    attachedFiles: files, setAttachedFiles: setFiles,
    isAttachmentDisabled: disabled, allowImages,
    focusTargetRef: inputRef, notifyAttachmentError: notifyError,
  });
  const { handlePaste, isPasting } = useChatClipboardPaste({
    inputRef, setInputValue: setValue, attachSelectedFiles,
    notifyError, isDisabled: disabled, scopeKey: `${scopeKey}:${allowImages}`,
  });
  return <>
    <textarea aria-label="input" ref={inputRef} value={value} onChange={(event) => setValue(event.target.value)} />
    <button onClick={() => { void handlePaste(); }}>paste</button>
    <output aria-label="pending">{String(isPasting)}</output>
    <output aria-label="files">{JSON.stringify(files)}</output>
  </>;
}

function input() { return screen.getByRole("textbox") as HTMLTextAreaElement; }
function paste() { fireEvent.click(screen.getByRole("button", { name: "paste" })); }

describe("composer clipboard paste", () => {
  it("reads only on click, replaces the selection, and restores focus and the caret", async () => {
    const read = vi.fn(async () => [textItem("貼り付け")]);
    setClipboard({ read });
    render(<Harness />);
    expect(read).not.toHaveBeenCalled();
    input().setSelectionRange(1, 2);
    paste();
    expect(read).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(input()).toHaveValue("前貼り付け"));
    expect(input()).toHaveFocus();
    expect(input().selectionStart).toBe(5);
    expect(input().selectionEnd).toBe(5);
  });

  it("falls back to text-only reading when read is unavailable", async () => {
    setClipboard({ readText: vi.fn(async () => "文章") });
    render(<Harness />);
    input().setSelectionRange(1, 1);
    paste();
    await waitFor(() => expect(input()).toHaveValue("前文章後"));
  });

  it("attaches an image through the existing pipeline without pasting its alternate text", async () => {
    const item = imageItem();
    setClipboard({ read: vi.fn(async () => [textItem("https://example.test/image"), item]) });
    render(<Harness />);
    paste();
    await waitFor(() => expect(JSON.parse(screen.getByLabelText("files").textContent!)).toHaveLength(1));
    const files = JSON.parse(screen.getByLabelText("files").textContent!);
    expect(files[0]).toMatchObject({ mediaType: "image/webp", previewUrl: "data:image/webp;base64,aW1hZ2U=" });
    expect(files[0].name).toMatch(/^paste-.*\.png$/);
    expect(input()).toHaveValue("前後");
    expect(item.getType).toHaveBeenCalledExactlyOnceWith("image/png");
  });

  it("gives successive pasted images different names so neither is dropped as a duplicate", async () => {
    setClipboard({ read: vi.fn(async () => [imageItem()]) });
    render(<Harness />);
    paste();
    await waitFor(() => expect(JSON.parse(screen.getByLabelText("files").textContent!)).toHaveLength(1));
    paste();
    await waitFor(() => expect(JSON.parse(screen.getByLabelText("files").textContent!)).toHaveLength(2));
    const files = JSON.parse(screen.getByLabelText("files").textContent!);
    expect(files[0].name).not.toBe(files[1].name);
  });

  it("keeps the model restriction on pasted images", async () => {
    setClipboard({ read: vi.fn(async () => [imageItem()]) });
    render(<Harness allowImages={false} />);
    paste();
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith(expect.stringContaining("GPT-6 Luna")));
    expect(screen.getByLabelText("files")).toHaveTextContent("[]");
  });

  it("keeps the attachment limit on images while still allowing text paste", async () => {
    const read = vi.fn(async (): Promise<unknown[]> => [imageItem()]);
    setClipboard({ read });
    render(<Harness full />);
    paste();
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith("添付できるファイルは5件までです。"));
    read.mockResolvedValue([textItem("文章")]);
    input().setSelectionRange(2, 2);
    paste();
    await waitFor(() => expect(input()).toHaveValue("前後文章"));
    expect(JSON.parse(screen.getByLabelText("files").textContent!)).toHaveLength(5);
  });

  it.each([[], [textItem("")]])(
    "explains when clipboard contents cannot be pasted (%j)", async (...items) => {
      setClipboard({ read: vi.fn(async () => items.flat()) });
      render(<Harness />);
      paste();
      await waitFor(() => expect(notifyError).toHaveBeenCalledWith("貼り付けられる文章や画像がありません。"));
      expect(input()).toHaveValue("前後");
    },
  );

  it("explains unsupported clipboard formats and suggests file attachment", async () => {
    setClipboard({ read: async () => [{ types: ["text/html"], getType: vi.fn() }] });
    render(<Harness />);
    paste();
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith(expect.stringContaining("この形式はペーストできません")));
    expect(notifyError).toHaveBeenCalledWith(expect.stringContaining("ファイル添付"));
    expect(input()).toHaveValue("前後");
  });

  it.each([undefined, { read: vi.fn(async () => { throw new DOMException("denied", "NotAllowedError"); }) }])(
    "explains how to paste when clipboard reading is unavailable or denied", async (clipboard) => {
      setClipboard(clipboard);
      render(<Harness />);
      paste();
      await waitFor(() => expect(notifyError).toHaveBeenCalledWith(expect.stringContaining("長押し")));
      expect(input()).toHaveValue("前後");
      expect(screen.getByLabelText("pending")).toHaveTextContent("false");
    },
  );

  it("does not read when disabled", () => {
    const read = vi.fn();
    setClipboard({ read });
    render(<Harness disabled />);
    paste();
    expect(read).not.toHaveBeenCalled();
  });

  it("ignores duplicate clicks and preserves edits made while permission is pending", async () => {
    let finish!: (items: ReturnType<typeof textItem>[]) => void;
    const read = vi.fn(() => new Promise<ReturnType<typeof textItem>[]>((resolve) => { finish = resolve; }));
    setClipboard({ read });
    render(<Harness />);
    paste();
    paste();
    expect(read).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("pending")).toHaveTextContent("true");
    fireEvent.change(input(), { target: { value: "編集済み" } });
    input().setSelectionRange(4, 4);
    await act(async () => { finish([textItem("追加")]); });
    expect(input()).toHaveValue("編集済み追加");
  });

  it.each(["disable", "room", "unmount"])("discards a pending read after %s", async (change) => {
    let finish!: (items: ReturnType<typeof textItem>[]) => void;
    setClipboard({ read: () => new Promise<ReturnType<typeof textItem>[]>((resolve) => { finish = resolve; }) });
    const view = render(<Harness />);
    paste();
    if (change === "disable") view.rerender(<Harness disabled />);
    else if (change === "room") view.rerender(<Harness scopeKey="room-b" />);
    else view.unmount();
    await act(async () => { finish([textItem("追加")]); });
    if (change !== "unmount") expect(input()).toHaveValue("前後");
    expect(notifyError).not.toHaveBeenCalled();
  });

  it("allows a new room to paste while the previous room's read is still pending", async () => {
    let finish!: (items: ReturnType<typeof textItem>[]) => void;
    const read = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue([textItem("新しい部屋")]);
    setClipboard({ read });
    const view = render(<Harness />);
    paste();
    view.rerender(<Harness scopeKey="room-b" />);
    expect(screen.getByLabelText("pending")).toHaveTextContent("false");
    input().setSelectionRange(2, 2);
    paste();
    await waitFor(() => expect(input()).toHaveValue("前後新しい部屋"));
    await act(async () => { finish([textItem("古い部屋")]); });
    expect(input()).toHaveValue("前後新しい部屋");
    expect(read).toHaveBeenCalledTimes(2);
  });

  it.each(["room", "disable", "model"])("discards image conversion that finishes after changing %s", async (change) => {
    let finish!: (image: Awaited<ReturnType<typeof downscaleChatImage>>) => void;
    vi.mocked(downscaleChatImage).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    setClipboard({ read: async () => [imageItem()] });
    const view = render(<Harness />);
    paste();
    await waitFor(() => expect(finish).toBeDefined());
    if (change === "room") view.rerender(<Harness scopeKey="room-b" />);
    else if (change === "disable") view.rerender(<Harness disabled />);
    else view.rerender(<Harness allowImages={false} />);
    await act(async () => { finish({ dataBase64: "aW1hZ2U=", mediaType: "image/webp", size: 5 }); });
    expect(screen.getByLabelText("files")).toHaveTextContent("[]");
  });
});
