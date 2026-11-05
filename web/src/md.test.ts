import { describe, expect, it } from "vitest";

import { parseInline, parseMarkdown } from "./md";

describe("report markdown", () => {
  it("reads headings, bold paragraphs, tables, bullets and code", () => {
    const blocks = parseMarkdown(
      ["# Run r1: passed", "", "**Result:** All tasks passed.", "", "## Tasks", "", "| Role | Result |", "|---|---|", "| qa | pass |", "", "- one", "- two", "", "```", "git diff", "```"].join("\n"),
    );
    expect(blocks.map((b) => b.type)).toEqual(["heading", "para", "heading", "table", "list", "code"]);
    expect(blocks[3]).toEqual({ type: "table", head: ["Role", "Result"], rows: [["qa", "pass"]] });
    expect(blocks[4]).toEqual({ type: "list", items: ["one", "two"] });
    expect(blocks[5]).toEqual({ type: "code", text: "git diff" });
  });

  it("splits inline bold and code, and leaves other text alone", () => {
    expect(parseInline("**Request:** run `make`, 2 * 3")).toEqual([
      { kind: "bold", text: "Request:" },
      { kind: "text", text: " run " },
      { kind: "code", text: "make" },
      { kind: "text", text: ", 2 * 3" },
    ]);
  });

  it("never turns text into markup: angle brackets stay text", () => {
    expect(parseInline("<script>alert(1)</script>")).toEqual([{ kind: "text", text: "<script>alert(1)</script>" }]);
  });

  it("survives an unterminated code fence", () => {
    expect(parseMarkdown("```\nabc")).toEqual([{ type: "code", text: "abc" }]);
  });
});
