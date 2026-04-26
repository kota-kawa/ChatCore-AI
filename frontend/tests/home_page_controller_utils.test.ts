import assert from "node:assert/strict";
import test from "node:test";

import { buildTaskOrderForPersistence } from "../lib/chat_page/home_page_controller_utils";

test("buildTaskOrderForPersistence excludes default tasks and empty names", () => {
  const order = buildTaskOrderForPersistence([
    {
      name: "Default Task",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: true,
    },
    {
      name: "  Create report  ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      name: "   ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      name: "Send summary",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
  ]);

  assert.deepEqual(order, ["Create report", "Send summary"]);
});
