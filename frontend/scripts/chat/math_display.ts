import { replaceDisplayText, type DisplaySourceSpan } from "./display_source_positions";

function readBracedGroup(value: string, startIndex: number) {
  if (value[startIndex] !== "{") return null;

  let depth = 0;
  for (let index = startIndex; index < value.length; index += 1) {
    const char = value[index];
    if (char === "{") {
      depth += 1;
      continue;
    }
    if (char !== "}") continue;
    depth -= 1;
    if (depth === 0) {
      return {
        content: value.slice(startIndex + 1, index),
        endIndex: index + 1,
      };
    }
  }

  return null;
}

function replaceLatexFractions(value: string, positions?: DisplaySourceSpan[]) {
  let output = value;
  for (let pass = 0; pass < 4; pass += 1) {
    const commandIndex = output.search(/\\d?frac\{/);
    if (commandIndex < 0) break;

    const command = output.startsWith("\\dfrac", commandIndex) ? "\\dfrac" : "\\frac";
    const numerator = readBracedGroup(output, commandIndex + command.length);
    if (!numerator) break;
    const denominator = readBracedGroup(output, numerator.endIndex);
    if (!denominator) break;

    if (positions) {
      const numeratorStart = commandIndex + command.length;
      const denominatorStart = numerator.endIndex;
      const replacementSpans = [
        positions[numeratorStart],
        ...positions.slice(numeratorStart + 1, numerator.endIndex - 1),
        positions[numerator.endIndex - 1],
        positions[numerator.endIndex - 1],
        positions[denominatorStart],
        ...positions.slice(denominatorStart + 1, denominator.endIndex - 1),
        positions[denominator.endIndex - 1],
      ];
      positions.splice(commandIndex, denominator.endIndex - commandIndex, ...replacementSpans);
    }
    output = [
      output.slice(0, commandIndex),
      `(${numerator.content})/(${denominator.content})`,
      output.slice(denominator.endIndex),
    ].join("");
  }
  return output;
}

export function formatMathExpressionForDisplay(value: string, positions?: DisplaySourceSpan[]) {
  let output = replaceLatexFractions(value, positions);
  output = replaceDisplayText(output, /\\left\s*/g, "", positions);
  output = replaceDisplayText(output, /\\right\s*/g, "", positions);
  output = replaceDisplayText(output, /\\begin\{cases\}/g, "{", positions);
  output = replaceDisplayText(output, /\\end\{cases\}/g, "", positions);
  output = replaceDisplayText(output, /\\\[\s*\d+(?:\.\d+)?(?:pt|em|ex|px)\s*\]/g, "", positions);
  output = replaceDisplayText(output, /\\\\/g, "", positions);
  output = replaceDisplayText(output, /\s*&\s*/g, "    ", positions);
  output = replaceDisplayText(output, /\\qquad/g, "    ", positions);
  output = replaceDisplayText(output, /\\quad/g, "  ", positions);
  output = replaceDisplayText(output, /\\lambda/g, "λ", positions);
  output = replaceDisplayText(output, /\\mu/g, "μ", positions);
  output = replaceDisplayText(output, /\\rho/g, "ρ", positions);
  output = replaceDisplayText(output, /\\sum/g, "∑", positions);
  output = replaceDisplayText(output, /\\leq?/g, "≤", positions);
  output = replaceDisplayText(output, /\\geq?/g, "≥", positions);
  output = replaceDisplayText(output, /\\neq/g, "≠", positions);
  output = replaceDisplayText(output, /\\infty/g, "∞", positions);
  output = replaceDisplayText(output, /\\cdot/g, "⋅", positions);
  output = replaceDisplayText(output, /\\times/g, "×", positions);
  output = replaceDisplayText(output, /,\s*/g, ", ", positions);
  output = replaceDisplayText(output, /\s{5,}/g, "    ", positions);
  return replaceDisplayText(output, /^\s+|\s+$/g, "", positions);
}

export function looksLikeLooseMathLine(line: string) {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return (
    /\\(?:d?frac|sum|rho|lambda|mu|begin|end|leq?|geq?|left|right|qquad|quad)/.test(trimmed) ||
    /^[A-Za-z][A-Za-z0-9_{}^]*\s*=/.test(trimmed) ||
    /[_^].*=/.test(trimmed)
  );
}

