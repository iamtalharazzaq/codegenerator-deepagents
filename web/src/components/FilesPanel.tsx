import { ChevronRight, Download, File, FileText, Folder, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import { useData } from "../data";
import { fileTree, runFiles, type FileNode, type RunView } from "../model";
import { agentToken } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { buttonClass, Collapse, CopyButton, cx, Skeleton } from "../ui/bits";
import { Markdown } from "../ui/Markdown";

function Node({ node, depth, selected, onSelect }: { node: FileNode; depth: number; selected: string | null; onSelect: (path: string) => void }) {
  const [open, setOpen] = useState(true);
  const pad = { paddingLeft: 8 + depth * 16 };
  if (node.children.length === 0) {
    const on = selected === node.path;
    const Icon = /\.(md|txt)$/.test(node.name) ? FileText : File;
    return (
      <li>
        <button type="button" onClick={() => onSelect(node.path)} aria-current={on ? "true" : undefined} style={pad} className={cx("flex h-9 w-full items-center gap-2 rounded-lg pr-2 text-left transition-colors", on ? "bg-raised text-fg" : "text-fg-2 hover:bg-raised/60 hover:text-fg")}>
          <Icon size={16} aria-hidden className="shrink-0 text-fg-3" />
          <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{node.name}</span>
          {node.file && <AgentAvatar role={node.file.role} size="sm" className="!size-6 !rounded-md" />}
        </button>
      </li>
    );
  }
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} style={pad} className="flex h-9 w-full items-center gap-2 rounded-lg pr-2 text-left text-fg hover:bg-raised/60">
        <ChevronRight size={14} aria-hidden className={cx("shrink-0 text-fg-3 transition-transform duration-200", open && "rotate-90")} />
        {open ? <FolderOpen size={16} aria-hidden className="shrink-0 text-accent" /> : <Folder size={16} aria-hidden className="shrink-0 text-accent" />}
        <span className="truncate font-mono text-[13px]">{node.name}</span>
      </button>
      <Collapse open={open}>
        <ul>{node.children.map((c) => <Node key={c.path} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />)}</ul>
      </Collapse>
    </li>
  );
}

function Preview({ view, path }: { view: RunView; path: string }) {
  const source = useData();
  const [body, setBody] = useState<string | null | undefined>(undefined);
  const entry = view.files.find((f) => f.path.replace(/^\/+/, "") === path);
  useEffect(() => {
    if (!view.runId) return;
    let live = true;
    setBody(undefined);
    source.file(view.runId, path).then((t) => live && setBody(t)).catch(() => live && setBody(null));
    return () => { live = false; };
  }, [view.runId, path, source]);
  return (
    <div className="raised overflow-hidden" aria-label={`Preview of ${path}`} role="region">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-4 py-3">
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-medium" title={path}>{path}</span>
        {entry && <span className="text-[13px] text-fg-3">written by {agentToken(entry.role).label}</span>}
        {body && <CopyButton text={path} label="Copy path" />}
      </div>
      <div className="p-4">
        {body === undefined ? <div className="space-y-2" aria-busy="true"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4" /><Skeleton className="h-4 w-4/5" /></div>
          : body === null ? <p className="text-fg-2">This file cannot be previewed. It is still in the zip.</p>
          : /\.md$/.test(path) ? <Markdown text={body} />
          : <pre className="whitespace-pre-wrap break-words font-mono text-[13px] leading-6 text-fg-2">{body}</pre>}
      </div>
    </div>
  );
}

/** The Files tab: every file the agents wrote as a folder tree, a preview of the selected file, and the zip. */
export function FilesPanel({ view }: { view: RunView }) {
  const paths = runFiles(view);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { setSelected(null); }, [view.runId]);
  const current = selected && paths.includes(selected) ? selected : paths.find((p) => /\.(md|html|js|py|ts)$/.test(p)) ?? paths[0] ?? null;
  const tree = fileTree(paths, view.files);
  const zip = view.runId && view.status === "passed" && view.zip ? `/api/runs/${view.runId}/delivery.zip` : view.runId && view.tasks.length && view.status !== "running" ? `/api/runs/${view.runId}/delivery.zip?partial=1` : null;
  return (
    <section aria-labelledby="files-title" className="space-y-4">
      <div className="surface p-5">
        <div className="mb-3 flex items-center gap-3">
          <h2 id="files-title" className="flex-1 text-[17px] font-semibold tracking-tight">Files <span className="ml-1 text-[13px] font-normal text-fg-3">{paths.length}</span></h2>
          {zip && <a href={zip} download className={buttonClass(view.status === "passed" ? "primary" : "secondary", "sm")}><Download size={14} aria-hidden />{view.status === "passed" ? "Download zip" : "Partial zip"}</a>}
        </div>
        {paths.length === 0
          ? <p className="py-6 text-center text-fg-3">{view.status === "running" ? "Files appear here as the agents write them." : "No files were written in this run."}</p>
          : <ul aria-label="Generated files">{tree.map((n) => <Node key={n.path} node={n} depth={0} selected={current} onSelect={setSelected} />)}</ul>}
      </div>
      {current && <Preview view={view} path={current} />}
    </section>
  );
}
