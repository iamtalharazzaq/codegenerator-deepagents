import { parseInline, parseMarkdown } from "../md";

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((p, i) =>
        p.kind === "bold" ? <strong key={i}>{p.text}</strong> : p.kind === "code" ? <code key={i}>{p.text}</code> : <span key={i}>{p.text}</span>,
      )}
    </>
  );
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {parseMarkdown(text).map((b, i) => {
        switch (b.type) {
          case "heading": return b.level === 1 ? <h2 key={i}><Inline text={b.text} /></h2> : <h3 key={i}><Inline text={b.text} /></h3>;
          case "para": return <p key={i}><Inline text={b.text} /></p>;
          case "list": return <ul key={i}>{b.items.map((it, j) => <li key={j}><Inline text={it} /></li>)}</ul>;
          case "code": return <pre key={i}>{b.text}</pre>;
          case "table":
            return (
              <div className="table-wrap" key={i}>
                <table>
                  <thead><tr>{b.head.map((h, j) => <th key={j}>{h}</th>)}</tr></thead>
                  <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}><Inline text={c} /></td>)}</tr>)}</tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}
