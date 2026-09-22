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

function replaceLatexFractions(value: string) {
  let output = value;
  for (let pass = 0; pass < 4; pass += 1) {
    const commandIndex = output.search(/\\d?frac\{/);
    if (commandIndex < 0) break;

    const command = output.startsWith("\\dfrac", commandIndex) ? "\\dfrac" : "\\frac";
    const numerator = readBracedGroup(output, commandIndex + command.length);
    if (!numerator) break;
    const denominator = readBracedGroup(output, numerator.endIndex);
    if (!denominator) break;

    output = [
      output.slice(0, commandIndex),
      `(${numerator.content})/(${denominator.content})`,
      output.slice(denominator.endIndex),
    ].join("");
  }
  return output;
}

export function formatMathExpressionForDisplay(value: string) {
  return replaceLatexFractions(value)
    .replace(/\\left\s*/g, "")
    .replace(/\\right\s*/g, "")
    .replace(/\\begin\{cases\}/g, "{")
    .replace(/\\end\{cases\}/g, "")
    .replace(/\\\[\s*\d+(?:\.\d+)?(?:pt|em|ex|px)\s*\]/g, "")
    .replace(/\\\\/g, "")
    .replace(/\s*&\s*/g, "    ")
    .replace(/\\qquad/g, "    ")
    .replace(/\\quad/g, "  ")
    .replace(/\\lambda/g, "λ")
    .replace(/\\mu/g, "μ")
    .replace(/\\rho/g, "ρ")
    .replace(/\\sum/g, "∑")
    .replace(/\\leq?/g, "≤")
    .replace(/\\geq?/g, "≥")
    .replace(/\\neq/g, "≠")
    .replace(/\\infty/g, "∞")
    .replace(/\\cdot/g, "⋅")
    .replace(/\\times/g, "×")
    .replace(/,\s*/g, ", ")
    .replace(/\s{5,}/g, "    ")
    .trim();
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

