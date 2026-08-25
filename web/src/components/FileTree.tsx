"use client";

/** Collapsible directory tree over the indexed paths. */

import { useMemo, useState } from "react";

type Node = { name: string; path: string; children: Map<string, Node> };

function build(paths: string[]): Node {
  const root: Node = { name: "", path: "", children: new Map() };
  for (const path of paths) {
    let node = root;
    const parts = path.split("/");
    parts.forEach((part, index) => {
      const child = node.children.get(part) ?? {
        name: part,
        path: parts.slice(0, index + 1).join("/"),
        children: new Map(),
      };
      node.children.set(part, child);
      node = child;
    });
  }
  return root;
}

function Entry({
  node,
  depth,
  openPath,
  onOpen,
}: {
  node: Node;
  depth: number;
  openPath: string | null;
  onOpen: (path: string) => void;
}) {
  const isDir = node.children.size > 0;
  // Top-level directories start open; deeper ones stay collapsed so the
  // tree is scannable on a big repo.
  const [expanded, setExpanded] = useState(depth < 1);

  if (!isDir) {
    const active = openPath === node.path;
    return (
      <li>
        <button
          type="button"
          onClick={() => onOpen(node.path)}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
          className={`w-full truncate py-[3px] text-left font-mono text-xs
            hover:bg-surface-raised ${
              active
                ? "bg-surface-raised text-accent"
                : "text-foreground/75"
            }`}
        >
          {node.name}
        </button>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        className="w-full truncate py-[3px] text-left font-mono text-xs
          text-foreground/55 hover:bg-surface-raised"
        aria-expanded={expanded}
      >
        {expanded ? "▾" : "▸"} {node.name}/
      </button>
      {expanded && (
        <ul>
          {[...node.children.values()]
            .sort((a, b) => {
              const aDir = a.children.size > 0 ? 0 : 1;
              const bDir = b.children.size > 0 ? 0 : 1;
              return aDir - bDir || a.name.localeCompare(b.name);
            })
            .map((child) => (
              <Entry
                key={child.path}
                node={child}
                depth={depth + 1}
                openPath={openPath}
                onOpen={onOpen}
              />
            ))}
        </ul>
      )}
    </li>
  );
}

export function FileTree({
  paths,
  openPath,
  onOpen,
}: {
  paths: string[];
  openPath: string | null;
  onOpen: (path: string) => void;
}) {
  const root = useMemo(() => build(paths), [paths]);
  return (
    <nav aria-label="Files" className="overflow-auto">
      <ul>
        {[...root.children.values()]
          .sort((a, b) => {
            const aDir = a.children.size > 0 ? 0 : 1;
            const bDir = b.children.size > 0 ? 0 : 1;
            return aDir - bDir || a.name.localeCompare(b.name);
          })
          .map((child) => (
            <Entry
              key={child.path}
              node={child}
              depth={0}
              openPath={openPath}
              onOpen={onOpen}
            />
          ))}
      </ul>
    </nav>
  );
}
