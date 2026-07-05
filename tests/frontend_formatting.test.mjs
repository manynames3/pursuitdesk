import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const helperSource = [
  extractFunction("proposalMarkdownBlocks"),
  extractFunction("normalizeProposalMarkdown"),
  extractFunction("isMarkdownTableLine"),
  extractFunction("splitMarkdownTableRow"),
  extractFunction("isMarkdownSeparatorRow"),
  extractFunction("markdownTableToBullets"),
  extractFunction("cleanMarkdownText"),
  extractFunction("sanitizePdfText"),
  "globalThis.helpers = { proposalMarkdownBlocks, normalizeProposalMarkdown, sanitizePdfText };",
].join("\n");

const context = {};
vm.createContext(context);
vm.runInContext(helperSource, context);

function extractFunction(name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} exists in frontend/app.js`);
  const next = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, next === -1 ? source.length : next);
}

test("proposal Markdown tables become reviewer-friendly bullets", () => {
  const markdown = [
    "| Requirement | Response | Source |",
    "|---|---|---|",
    "| **Staffing** | Named PM and QA lead | [SAM.gov](https://sam.gov) |",
  ].join("\n");

  assert.equal(
    context.helpers.normalizeProposalMarkdown(markdown),
    "- Requirement: Staffing; Response: Named PM and QA lead; Source: SAM.gov (https://sam.gov)",
  );
});

test("proposal block parser removes raw Markdown formatting", () => {
  const blocks = context.helpers.proposalMarkdownBlocks("## Technical Approach\n- **Use `zero-trust` controls**");

  assert.deepEqual(JSON.parse(JSON.stringify(blocks)), [
    { type: "heading", level: 2, text: "Technical Approach" },
    { type: "bullet", text: "Use zero-trust controls" },
  ]);
});

test("PDF text sanitizer normalizes smart punctuation and bullets", () => {
  assert.equal(
    context.helpers.sanitizePdfText("“Prime-ready” • validate source — before delivery"),
    "\"Prime-ready\" - validate source - before delivery",
  );
});
