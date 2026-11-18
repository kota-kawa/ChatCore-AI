// Render Markdown tokens as React nodes. HTML and images stay inert; links only
// navigate after an explicit click and open in a separate, isolated tab.
import { createElement, type ReactNode } from "react";
import { Lexer, type Token, type Tokens } from "marked";

function safeExternalHref(value: string): string | null {
  if (value.length > 2000) return null;
  try {
    const url = new URL(value);
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.host || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function renderToken(token: Token, key: string): ReactNode {
  switch (token.type) {
    case "space":
    case "def":
      return null;
    case "text":
      return token.tokens ? renderTokens(token.tokens, key) : token.text;
    case "escape":
      return token.text;
    case "strong":
      return <strong key={key}>{renderTokens(token.tokens ?? [], `${key}-strong`)}</strong>;
    case "em":
      return <em key={key}>{renderTokens(token.tokens ?? [], `${key}-em`)}</em>;
    case "del":
      return <del key={key}>{renderTokens(token.tokens ?? [], `${key}-del`)}</del>;
    case "codespan":
      return <code key={key}>{token.text}</code>;
    case "br":
      return <br key={key} />;
    case "html":
      return <span key={key} className="structured-ui__raw-markup">{token.text}</span>;
    case "link": {
      const href = safeExternalHref(token.href);
      return href ? (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer">
          {renderTokens(token.tokens ?? [], `${key}-link`)}
        </a>
      ) : renderTokens(token.tokens ?? [], `${key}-link-text`);
    }
    case "image":
      return <span key={key} className="structured-ui__image-alt">{renderTokens(token.tokens ?? [], `${key}-image-alt`)}</span>;
    case "code":
      return <pre key={key}><code>{token.text}</code></pre>;
    case "heading": {
      const tag = `h${Math.max(1, Math.min(6, token.depth))}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      return createElement(tag, { key }, renderTokens(token.tokens ?? [], `${key}-heading`));
    }
    case "paragraph":
      return <p key={key}>{renderTokens(token.tokens ?? [], `${key}-paragraph`)}</p>;
    case "blockquote":
      return <blockquote key={key}>{renderTokens(token.tokens ?? [], `${key}-quote`)}</blockquote>;
    case "hr":
      return <hr key={key} />;
    case "list": {
      const list = token as Tokens.List;
      const tag = list.ordered ? "ol" : "ul";
      return createElement(
        tag,
        { key, ...(list.ordered && typeof list.start === "number" ? { start: list.start } : {}) },
        list.items.map((item, index) => renderListItem(item, `${key}-item-${index}`)),
      );
    }
    case "list_item":
      return renderListItem(token as Tokens.ListItem, key);
    case "checkbox":
      return <span key={key} className="structured-ui__markdown-checkbox" aria-label={token.checked ? "checked" : "not checked"}>{token.checked ? "✓" : "□"}</span>;
    case "table": {
      const table = token as Tokens.Table;
      return (
        <div key={key} className="structured-ui__table-scroll">
          <table>
            <thead><tr>{table.header.map((cell, index) => renderTableCell(cell, `${key}-header-${index}`, true))}</tr></thead>
            <tbody>{table.rows.map((row, rowIndex) => <tr key={`${key}-row-${rowIndex}`}>
              {row.map((cell, columnIndex) => renderTableCell(cell, `${key}-row-${rowIndex}-cell-${columnIndex}`, false))}
            </tr>)}</tbody>
          </table>
        </div>
      );
    }
    default:
      return token.raw;
  }
}

function renderListItem(item: Tokens.ListItem, key: string): ReactNode {
  return <li key={key}>{renderTokens(item.tokens, `${key}-content`)}</li>;
}

function renderTableCell(cell: Tokens.TableCell, key: string, header: boolean): ReactNode {
  const tag = header ? "th" : "td";
  return createElement(tag, { key, scope: header ? "col" : undefined }, renderInline(cell.tokens, `${key}-content`));
}

function renderInline(tokens: Token[], keyPrefix: string): ReactNode[] {
  return tokens.map((token, index) => renderToken(token, `${keyPrefix}-${index}`));
}

function renderTokens(tokens: Token[], keyPrefix: string): ReactNode[] {
  return tokens.map((token, index) => renderToken(token, `${keyPrefix}-${index}`));
}

type Props = { text: string };

export function StructuredUiMarkdown({ text }: Props) {
  const tokens = Lexer.lex(text, { gfm: true, breaks: true });
  return <div className="structured-ui__markdown">{renderTokens(tokens, "markdown")}</div>;
}

export function StructuredUiInlineMarkdown({ text }: Props) {
  const tokens = Lexer.lexInline(text, { gfm: true, breaks: true });
  return <span className="structured-ui__inline-markdown">{renderInline(tokens, "inline-markdown")}</span>;
}
