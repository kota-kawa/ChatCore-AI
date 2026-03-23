export type PromptRecord = {
  id?: string | number;
  title: string;
  content: string;
  category: string;
  inputExamples: string;
  outputExamples: string;
  createdAt?: string;
};

const asString = (value: unknown) => {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return String(value);
};

const asId = (value: unknown) => {
  if (typeof value === "string" || typeof value === "number") return value;
  return undefined;
};

export const toPromptRecord = (raw: unknown): PromptRecord => {
  const obj = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  return {
    id: asId(obj.id),
    title: asString(obj.title),
    content: asString(obj.content),
    category: asString(obj.category),
    inputExamples: asString(obj.input_examples),
    outputExamples: asString(obj.output_examples),
    createdAt: asString(obj.created_at) || undefined
  };
};

export type PromptListEntry = {
  id?: string | number;
  promptId?: string | number;
  prompt: PromptRecord;
  title: string;
  content: string;
  category: string;
  inputExamples: string;
  outputExamples: string;
  createdAt?: string;
};

export const toPromptListEntry = (raw: unknown): PromptListEntry => {
  const obj = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const nestedPrompt = toPromptRecord(obj.prompt);
  const fallbackPrompt = toPromptRecord(obj);
  const prompt = nestedPrompt.title || nestedPrompt.content ? nestedPrompt : fallbackPrompt;
  return {
    id: asId(obj.id),
    promptId: asId(obj.prompt_id),
    prompt,
    title: prompt.title,
    content: prompt.content,
    category: prompt.category,
    inputExamples: prompt.inputExamples,
    outputExamples: prompt.outputExamples,
    createdAt: asString(obj.created_at) || undefined
  };
};
