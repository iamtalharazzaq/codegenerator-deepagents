/** A small markdown reader for the run report: headings, paragraphs, bullets, fenced code and tables.
 * It returns plain data; the component turns it into elements (nothing is ever injected as HTML). */

export type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "para"; text: string }
  | { type: "list"; items: string[] }
  | { type: "code"; text: string }
  | { type: "table"; head: string[]; rows: string[][] };

const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isSeparator = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push({ type: "code", text: body.join("\n") });
    } else if (/^#{1,4}\s/.test(line)) {
      const level = line.match(/^#+/)![0].length;
      blocks.push({ type: "heading", level, text: line.replace(/^#+\s*/, "") });
      i++;
    } else if (line.trim().startsWith("|") && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push({ type: "table", head, rows });
    } else if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      blocks.push({ type: "list", items });
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s+)/.test(lines[i]) && !lines[i].trim().startsWith("|")) para.push(lines[i++]);
      if (!para.length) para.push(lines[i++]);
      blocks.push({ type: "para", text: para.join(" ") });
    }
  }
  return blocks;
}

export type Inline = { kind: "text" | "bold" | "code"; text: string };

export function parseInline(text: string): Inline[] {
  return text
    .split(/(\*\*[^*]+\*\*|`[^`]+`)/)
    .filter(Boolean)
    .map((part): Inline =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4 ? { kind: "bold", text: part.slice(2, -2) }
        : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? { kind: "code", text: part.slice(1, -1) }
        : { kind: "text", text: part },
    );
}
