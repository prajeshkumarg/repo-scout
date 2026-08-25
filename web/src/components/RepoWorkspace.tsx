"use client";

/**
 * The repo shell: code browser on the left, chat on the right.
 *
 * Clicking a citation in an answer opens the file and highlights the
 * range — that wiring is the point of the layout, so it lives here
 * rather than being threaded through props from further away.
 */

import { useState } from "react";
import { Group, Panel, Separator, type Layout } from "react-resizable-panels";

import { ChatPanel } from "@/components/ChatPanel";
import { CodeViewer, type Range } from "@/components/CodeViewer";
import { EmbeddingIndicator } from "@/components/EmbeddingIndicator";
import { FileTree } from "@/components/FileTree";
import { IndexingOverlay } from "@/components/IndexingOverlay";
import { Orientation } from "@/components/Orientation";
import type { Orientation as OrientationPayload } from "@/lib/api";
import { useAgentRun, type CitationRef } from "@/lib/useAgentRun";

const LAYOUT_KEY = "repo-scout:workspace-layout";

/** A hairline divider that takes the accent while it is being dragged. */
function Divider() {
  return (
    <Separator
      className="group relative w-px shrink-0 bg-border outline-none
        transition-colors hover:bg-accent
        data-[state=dragging]:bg-accent"
    >
      {/* The line stays one pixel; the grab area is wider, or it is
          unusably fiddly to hit with a mouse. */}
      <span className="absolute inset-y-0 -left-1 -right-1 block" />
    </Separator>
  );
}

/** Remember an adjusted layout, so it survives a reload. */
function useStoredLayout(): [Layout | undefined, (layout: Layout) => void] {
  const [stored] = useState<Layout | undefined>(() => {
    if (typeof window === "undefined") return undefined;
    try {
      const raw = window.localStorage.getItem(LAYOUT_KEY);
      return raw ? (JSON.parse(raw) as Layout) : undefined;
    } catch {
      return undefined; // private mode, cleared storage: fall back to defaults
    }
  });
  const save = (layout: Layout) => {
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      // Not worth failing a resize over.
    }
  };
  return [stored, save];
}

export function RepoWorkspace({
  owner,
  name,
  orientation,
  tree,
  runId,
}: {
  owner: string;
  name: string;
  /** Absent while the repo is still being indexed for the first time. */
  orientation: OrientationPayload | null;
  tree: string[];
  runId: number | null;
}) {
  const repo = `${owner}/${name}`;
  const indexing = orientation === null;
  const { exchanges, running, ask, cancel } = useAgentRun(repo);

  const [openPath, setOpenPath] = useState<string | null>(
    orientation?.key_files[0] ?? null,
  );
  const [range, setRange] = useState<Range>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [storedLayout, saveLayout] = useStoredLayout();

  function openCitation(citation: CitationRef) {
    setOpenPath(citation.path);
    setRange({ start: citation.start, end: citation.end });
  }

  return (
    <div className="flex h-screen flex-col">
      <header
        className="flex items-baseline gap-3 border-b border-border
          bg-surface px-4 py-2"
      >
        <a href="/" className="text-sm font-semibold hover:underline">
          repo-scout
        </a>
        <span className="text-sm opacity-80">{repo}</span>
        <span className="font-mono text-xs opacity-50">
          {orientation ? orientation.sha.slice(0, 8) : "indexing"}
        </span>
        {/* Structure is ready but vectors may still be landing. */}
        {!indexing && runId !== null && <EmbeddingIndicator runId={runId} />}
        <span className="ml-auto text-xs opacity-50">
          {orientation ? `${tree.length} files indexed` : "reading the repo"}
        </span>
      </header>

      {/* Sizes are percentages: a bare number would mean pixels. */}
      <Group
        orientation="horizontal"
        defaultLayout={storedLayout}
        onLayoutChange={saveLayout}
        className="flex min-h-0 flex-1"
      >
        {/* Sidebar sits above the editor ground, as in VS Code. */}
        <Panel defaultSize="18%" minSize="10%" collapsible>
          <aside className="h-full overflow-auto bg-surface py-2">
            <FileTree
              paths={tree}
              openPath={openPath}
              onOpen={(path) => {
                setOpenPath(path);
                setRange(null);
              }}
            />
          </aside>
        </Panel>

        <Divider />

        <Panel defaultSize="48%" minSize="25%">
          <section className="h-full min-w-0">
            <CodeViewer
              owner={owner}
              name={name}
              path={openPath}
              range={range}
              onJump={(line) => setRange({ start: line, end: line })}
            />
          </section>
        </Panel>

        <Divider />

        {/* Chat is covered and inert until there is an index: a question
            asked now would have nothing to answer from. */}
        <Panel defaultSize="34%" minSize="20%">
          <aside className="relative flex h-full flex-col bg-surface">
            {indexing && runId !== null && <IndexingOverlay runId={runId} />}
            <ChatPanel
              disabled={indexing}
              exchanges={exchanges}
              running={running}
              onAsk={(question) => void ask(question)}
              onCancel={cancel}
              onCitation={openCitation}
              draft={draft}
              empty={
                orientation ? (
                  <Orientation
                    orientation={orientation}
                    onAsk={(question) => {
                      setDraft(question);
                      void ask(question);
                    }}
                  />
                ) : null
              }
            />
          </aside>
        </Panel>
      </Group>
    </div>
  );
}
