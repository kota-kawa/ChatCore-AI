import { Lexer, type Token } from "marked";

interface SourceCharacter {
  text: string;
  start: number;
  end: number;
}

// Map visible Markdown characters back to the source. Token boundaries keep repeated
// words in link destinations, fence labels and formatting syntax out of the search.
export function markdownSourceCharacters(source: string, doc: Document): SourceCharacter[] {
  const characters: SourceCharacter[] = [];
  const decoder = doc.createElement("textarea");

  function append(text: string, positions: number[], decodeEntities: boolean) {
    for (let i = 0; i < text.length; i++) {
      const entity = decodeEntities && text[i] === "&" && text.slice(i).match(/^&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);/i)?.[0];
      const raw = entity || text[i];
      if (entity) decoder.innerHTML = entity;
      const visible = entity ? decoder.value : raw;
      for (let j = 0; j < visible.length; j++) {
        if (!/\s/.test(visible[j])) {
          characters.push({ text: visible[j], start: positions[i], end: positions[i + raw.length - 1] + 1 });
        }
      }
      i += raw.length - 1;
    }
  }

  // Blockquotes/lists remove prefixes from continuation lines before lexing children.
  function locate(text: string, parent: string, positions: number[], from: number) {
    const exact = parent.indexOf(text, from);
    if (exact >= 0) return { positions: positions.slice(exact, exact + text.length), end: exact + text.length };
    const mapped: number[] = [];
    let cursor = from;
    for (const line of text.split("\n")) {
      const start = parent.indexOf(line, cursor);
      if (start < 0) return null;
      mapped.push(...positions.slice(start, start + line.length));
      cursor = start + line.length;
      if (mapped.length < text.length) {
        const newline = parent.indexOf("\n", cursor);
        if (newline < 0) return null;
        mapped.push(positions[newline]);
        cursor = newline + 1;
      }
    }
    return { positions: mapped, end: cursor };
  }

  function walk(tokens: Token[], parent: string, positions: number[]) {
    let cursor = 0;
    for (const token of tokens) {
      const located = locate(token.raw, parent, positions, cursor);
      if (!located) continue;
      cursor = located.end;
      const mapped = located.positions;
      if (token.type === "list") {
        walk(token.items, token.raw, mapped);
      } else if (token.type === "table") {
        walk([...token.header, ...token.rows.flat()].flatMap((cell) => cell.tokens), token.raw, mapped);
      } else if ("tokens" in token && token.tokens) {
        walk(token.tokens, token.raw, mapped);
      } else if (token.type === "html") {
        for (const match of token.raw.matchAll(/[^<>]+(?=<|$)/g)) {
          // Only text outside tags (including raw inline HTML) participates.
          if (match.index > 0 && token.raw[match.index - 1] === "<") continue;
          append(match[0], mapped.slice(match.index), true);
        }
      } else if (["text", "escape", "codespan", "code"].includes(token.type) && "text" in token) {
        const text = token.text;
        const contentStart = token.type === "code" && /^ {0,3}(`{3,}|~{3,})/.test(token.raw)
          ? token.raw.indexOf("\n") + 1 : 0;
        const content = locate(text, token.raw, mapped, contentStart);
        if (content) append(text, content.positions, token.type !== "code" && token.type !== "codespan");
      }
    }
  }

  const normalized = source.replace(/\r\n?/g, "\n");
  const positions: number[] = [];
  for (let i = 0; i < source.length; i++) {
    positions.push(i);
    if (source[i] === "\r" && source[i + 1] === "\n") i++;
  }
  walk(Lexer.lex(normalized, { gfm: true, breaks: true }), normalized, positions);
  return characters;
}

export function sourceOffsetAtCaret(root: HTMLElement, node: Node, offset: number, source: string): number | null {
  const characters = markdownSourceCharacters(source, root.ownerDocument);
  const visible = characters.map((character) => character.text).join("");
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const codeHeaders = Array.from(root.querySelectorAll("pre")).flatMap((pre) => {
    const wrapper = pre.parentElement;
    return wrapper && wrapper !== root && wrapper.tagName === "DIV"
      ? Array.from(wrapper.children).filter((child) => child !== pre && !child.contains(pre)) : [];
  });
  const boundary = node.nodeType !== Node.TEXT_NODE || !node.textContent?.trim()
    ? root.ownerDocument.createRange() : null;
  boundary?.setStart(node, offset);
  boundary?.collapse(true);
  let cursor = 0;
  for (let textNode = walker.nextNode(); textNode; textNode = walker.nextNode()) {
    if (codeHeaders.some((header) => header.contains(textNode))) continue;
    const text = textNode.textContent || "";
    const compact = text.replace(/\s/g, "");
    if (!compact) continue;
    const start = visible.indexOf(compact, cursor);
    if (start < 0) continue;
    if (boundary && boundary.comparePoint(textNode, 0) >= 0) return characters[start].start;
    if (textNode === node) {
      const before = text.slice(0, offset);
      const count = before.replace(/\s/g, "").length;
      if (!count) return characters[start].start;
      const previous = characters[start + count - 1];
      const spaces = before.match(/\s*$/)?.[0].length || 0;
      const next = characters[start + count];
      return Math.min(previous.end + spaces, next?.start ?? source.length);
    }
    cursor = start + compact.length;
  }
  return boundary && cursor > 0 ? characters[cursor - 1].end : null;
}
