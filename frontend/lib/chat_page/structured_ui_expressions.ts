// Evaluates the deliberately small expression graph used by native structured UI.
import {
  STRUCTURED_UI_MAX_EVALUATION_STEPS,
  STRUCTURED_UI_MAX_CHART_POINTS,
  type StructuredUiExpression,
  type StructuredUiRuntime,
  type StructuredUiScalar,
  type StructuredUiValue,
} from "./structured_ui_contract";

export type StructuredUiResult = StructuredUiScalar | Array<number | boolean> | undefined;

type NumericResult = number | number[];

function finiteNumber(value: StructuredUiResult): NumericResult | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value) && value.length <= STRUCTURED_UI_MAX_CHART_POINTS && value.every((item) => typeof item === "number" && Number.isFinite(item))) {
    return value as number[];
  }
  return undefined;
}

function numberAt(value: NumericResult, index: number): number {
  return Array.isArray(value) ? value[index] : value;
}

function vectorLength(values: NumericResult[]): number | null {
  const lengths = values.filter(Array.isArray).map((value) => value.length);
  if (!lengths.length) return null;
  if (lengths.some((length) => length !== lengths[0])) return -1;
  return lengths[0];
}

function mapNumeric(values: NumericResult[], operation: (numbers: number[]) => number): NumericResult | undefined {
  const length = vectorLength(values);
  if (length === -1 || (length !== null && length > STRUCTURED_UI_MAX_CHART_POINTS)) return undefined;
  if (length === null) {
    const output = operation(values as number[]);
    return Number.isFinite(output) ? output : undefined;
  }
  const output = Array.from({ length }, (_, index) => operation(values.map((value) => numberAt(value, index))));
  return output.every(Number.isFinite) ? output : undefined;
}

function stringifyState(value: StructuredUiScalar | undefined): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  return value ? "true" : "false";
}

/** One evaluator instance shares its instruction budget across every expression used by a render. */
export class StructuredUiExpressionEvaluator {
  private readonly states = new Map<string, StructuredUiScalar>();
  private readonly expressions = new Map<string, StructuredUiExpression>();
  private readonly activeExpressions = new Set<string>();
  private steps = 0;
  private exhausted = false;

  constructor(ui: StructuredUiRuntime, stateValues: Record<string, StructuredUiScalar>) {
    for (const [id, value] of Object.entries(stateValues)) this.states.set(id, value);
    for (const expression of ui.expressions) this.expressions.set(expression.id, expression);
  }

  evaluate(expressionId: string): StructuredUiResult {
    return this.evaluateExpression(expressionId, 0);
  }

  resolve(value: StructuredUiValue): StructuredUiResult {
    return this.resolveValue(value, 0);
  }

  get isExhausted(): boolean {
    return this.exhausted;
  }

  private takeStep(): boolean {
    this.steps += 1;
    if (this.steps <= STRUCTURED_UI_MAX_EVALUATION_STEPS) return true;
    this.exhausted = true;
    return false;
  }

  private resolveValue(value: StructuredUiValue, index: number): StructuredUiResult {
    if (!this.takeStep()) return undefined;
    switch (value.kind) {
      case "literal":
        return value.value;
      case "state":
        return this.states.get(String(value.value));
      case "expression":
        return this.evaluateExpression(String(value.value), index);
      case "index": {
        const offset = typeof value.value === "number" ? value.value : Number(value.value);
        return Number.isFinite(offset) ? index + offset : undefined;
      }
      default:
        return undefined;
    }
  }

  private evaluateExpression(expressionId: string, index: number): StructuredUiResult {
    if (!this.takeStep() || this.activeExpressions.has(expressionId)) return undefined;
    const expression = this.expressions.get(expressionId);
    if (!expression) return undefined;
    this.activeExpressions.add(expressionId);
    try {
      if (expression.op === "series") return this.evaluateSeries(expression.args, index);
      if (expression.op === "if") return this.evaluateIf(expression.args, index);
      if (expression.op === "and" || expression.op === "or") return this.evaluateLogical(expression.op, expression.args, index);
      const args = expression.args.map((arg) => this.resolveValue(arg, index));
      if (args.some((value) => value === undefined)) return undefined;
      return this.evaluateOperation(expression.op, args as Array<StructuredUiScalar | number[]>);
    } finally {
      this.activeExpressions.delete(expressionId);
    }
  }

  private evaluateSeries(args: StructuredUiValue[], index: number): number[] | undefined {
    if (args.length !== 2 || args[1].kind !== "expression") return undefined;
    const countValue = this.resolveValue(args[0], index);
    if (typeof countValue !== "number" || !Number.isInteger(countValue) || countValue < 0 || countValue > STRUCTURED_UI_MAX_CHART_POINTS) {
      return undefined;
    }
    const values: number[] = [];
    const expressionId = String(args[1].value);
    for (let pointIndex = 0; pointIndex < countValue; pointIndex += 1) {
      const value = this.evaluateExpression(expressionId, pointIndex);
      if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
      values.push(value);
      if (this.exhausted) return undefined;
    }
    return values;
  }

  private evaluateOperation(op: string, args: Array<StructuredUiScalar | number[]>): StructuredUiResult {
    switch (op) {
      case "add":
        return this.numericOperation(args, (values) => values.reduce((sum, value) => sum + value, 0));
      case "sub":
        return this.numericOperation(args, (values) => values[0] - values[1]);
      case "mul":
        return this.numericOperation(args, (values) => values.reduce((product, value) => product * value, 1));
      case "div":
        return this.numericOperation(args, (values) => values[0] / values[1]);
      case "pow":
        return this.numericOperation(args, (values) => values[0] ** values[1]);
      case "payment":
        return this.numericOperation(args, ([principal, rate, periods]) => {
          if (principal < 0 || rate < 0 || periods <= 0) return Number.NaN;
          if (rate === 0) return principal / periods;
          return principal * rate / -Math.expm1(-periods * Math.log1p(rate));
        });
      case "min":
        return this.numericOperation(args, (values) => Math.min(...values));
      case "max":
        return this.numericOperation(args, (values) => Math.max(...values));
      case "round":
        return this.numericOperation(args, (values) => Math.round(values[0]));
      case "abs":
        return this.numericOperation(args, (values) => Math.abs(values[0]));
      case "eq":
        return this.compareOperation(args, (left, right) => left === right);
      case "lt":
        return this.numericCompareOperation(args, (left, right) => left < right);
      case "lte":
        return this.numericCompareOperation(args, (left, right) => left <= right);
      case "not":
        return this.booleanOperation(args, (values) => !values[0]);
      case "if":
        return this.evaluateConditional(args);
      case "sum":
        return this.sumOperation(args);
      default:
        return undefined;
    }
  }

  private numericOperation(
    args: Array<StructuredUiScalar | number[]>,
    operation: (values: number[]) => number,
  ): StructuredUiResult {
    const values = args.map(finiteNumber);
    if (values.some((value) => value === undefined)) return undefined;
    return mapNumeric(values as NumericResult[], operation);
  }

  private compareOperation(
    args: Array<StructuredUiScalar | number[]>,
    operation: (left: StructuredUiScalar, right: StructuredUiScalar) => boolean,
  ): StructuredUiResult {
    if (args.length !== 2) return undefined;
    const [left, right] = args;
    if (Array.isArray(left) || Array.isArray(right)) {
      const leftValues = Array.isArray(left) ? left : null;
      const rightValues = Array.isArray(right) ? right : null;
      const length = leftValues?.length ?? rightValues?.length ?? 0;
      if (leftValues && rightValues && leftValues.length !== rightValues.length) return undefined;
      if (length > STRUCTURED_UI_MAX_CHART_POINTS) return undefined;
      return Array.from({ length }, (_, index) => operation(
        (leftValues ? leftValues[index] : left) as StructuredUiScalar,
        (rightValues ? rightValues[index] : right) as StructuredUiScalar,
      )) as unknown as number[];
    }
    return operation(left, right);
  }

  private numericCompareOperation(args: Array<StructuredUiScalar | number[]>, operation: (left: number, right: number) => boolean): StructuredUiResult {
    const values = args.map(finiteNumber);
    if (values.some((value) => value === undefined) || values.length !== 2) return undefined;
    const [left, right] = values as NumericResult[];
    const length = vectorLength([left, right]);
    if (length === -1 || (length !== null && length > STRUCTURED_UI_MAX_CHART_POINTS)) return undefined;
    if (length === null) return operation(left as number, right as number);
    return Array.from({ length }, (_, index) => operation(numberAt(left, index), numberAt(right, index))) as unknown as number[];
  }

  private booleanOperation(args: Array<StructuredUiScalar | number[]>, operation: (values: StructuredUiScalar[]) => boolean): StructuredUiResult {
    if (args.some(Array.isArray)) {
      const arrays = args.filter(Array.isArray) as number[][];
      const length = arrays[0]?.length ?? 0;
      if (arrays.some((array) => array.length !== length) || length > STRUCTURED_UI_MAX_CHART_POINTS) return undefined;
      return Array.from({ length }, (_, index) => operation(args.map((value) => Array.isArray(value) ? value[index] : value))) as unknown as number[];
    }
    return operation(args as StructuredUiScalar[]);
  }

  private evaluateConditional(args: Array<StructuredUiScalar | number[]>): StructuredUiResult {
    if (args.length !== 3) return undefined;
    const [condition, yes, no] = args;
    if (Array.isArray(condition)) {
      const yesValues = Array.isArray(yes) ? yes : null;
      const noValues = Array.isArray(no) ? no : null;
      const length = condition.length;
      if (length > STRUCTURED_UI_MAX_CHART_POINTS || (yesValues && yesValues.length !== length) || (noValues && noValues.length !== length)) return undefined;
      return condition.map((test, index) => (test ? yesValues?.[index] ?? yes as number : noValues?.[index] ?? no as number));
    }
    return condition ? yes : no;
  }

  private evaluateIf(args: StructuredUiValue[], index: number): StructuredUiResult {
    if (args.length !== 3) return undefined;
    const condition = this.resolveValue(args[0], index);
    if (condition === undefined) return undefined;
    if (!Array.isArray(condition)) return this.resolveValue(condition ? args[1] : args[2], index);
    const yes = this.resolveValue(args[1], index);
    const no = this.resolveValue(args[2], index);
    if (yes === undefined || no === undefined) return undefined;
    return this.evaluateConditional([condition, yes, no] as Array<StructuredUiScalar | number[]>);
  }

  private evaluateLogical(op: "and" | "or", args: StructuredUiValue[], index: number): StructuredUiResult {
    const values: Array<StructuredUiScalar | number[]> = [];
    for (const arg of args) {
      const value = this.resolveValue(arg, index);
      if (value === undefined) return undefined;
      values.push(value as StructuredUiScalar | number[]);
      if (values.every((item) => !Array.isArray(item))) {
        if (op === "and" && !value) return false;
        if (op === "or" && value) return true;
      }
    }
    return this.booleanOperation(values, (resolved) => op === "and" ? resolved.every(Boolean) : resolved.some(Boolean));
  }

  private sumOperation(args: Array<StructuredUiScalar | number[]>): StructuredUiResult {
    let total = 0;
    for (const arg of args) {
      if (Array.isArray(arg)) {
        for (const value of arg) {
          if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
          total += value;
        }
      } else if (typeof arg === "number" && Number.isFinite(arg)) {
        total += arg;
      } else {
        return undefined;
      }
      if (!Number.isFinite(total)) return undefined;
    }
    return total;
  }
}

export function stateValueForCompose(value: StructuredUiScalar | undefined): string {
  return stringifyState(value);
}
