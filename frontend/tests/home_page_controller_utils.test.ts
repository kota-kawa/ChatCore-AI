import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTaskOrderForPersistence,
  isLatestChatTurnAnswered,
} from "../lib/chat_page/home_page_controller_utils";

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

test("isLatestChatTurnAnswered is true when an assistant reply follows the latest user message", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "assistant" },
    ]),
    true,
  );
});

test("isLatestChatTurnAnswered is false when the latest user message is still pending", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "assistant" },
      { sender: "user" },
    ]),
    false,
  );
});

test("isLatestChatTurnAnswered ignores thinking placeholders", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "thinking" },
    ]),
    false,
  );
});
