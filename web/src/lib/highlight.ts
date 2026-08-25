import "server-only";

/**
 * Syntax highlighting, server side.
 *
 * Shiki uses the same TextMate grammars as VS Code, so highlighting
 * matches what these files look like in an editor. It runs here rather
 * than in the browser: the highlighter and its grammars are large, and
 * the client only needs the resulting tokens.
 */

import { createHighlighter, type BundledLanguage } from "shiki";

/** Extension to Shiki language. Keys match what ingest indexes, plus
 *  the manifests and READMEs stored for orientation. */
const LANGUAGES: Record<string, BundledLanguage> = {
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  json: "json",
  toml: "toml",
  md: "markdown",
  yml: "yaml",
  yaml: "yaml",
};

const THEMES = { light: "github-light", dark: "github-dark" } as const;

export type Token = { content: string; color?: string; dark?: string };

// One highlighter per process: creating it loads grammars, which is far
// too expensive to repeat per request. The type comes from the call so
// it stays in step with whatever bundled languages Shiki resolves.
type Highlighter = Awaited<ReturnType<typeof createHighlighter>>;

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  highlighterPromise ??= createHighlighter({
    themes: [THEMES.light, THEMES.dark],
    langs: [...new Set(Object.values(LANGUAGES))],
  });
  return highlighterPromise;
}

export function languageFor(path: string): BundledLanguage | null {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return LANGUAGES[extension] ?? null;
}

/**
 * Tokenize a file into per-line tokens.
 *
 * Returns plain lines for anything we have no grammar for, so an
 * unknown extension degrades to readable text rather than failing.
 */
export async function highlight(
  code: string,
  path: string,
): Promise<Token[][]> {
  const lang = languageFor(path);
  if (!lang) return code.split("\n").map((line) => [{ content: line }]);

  const highlighter = await getHighlighter();
  const { tokens } = highlighter.codeToTokens(code, {
    lang,
    themes: THEMES,
  });
  return tokens.map((line) =>
    line.map((token) => ({
      content: token.content,
      color: token.htmlStyle?.color as string | undefined,
      dark: token.htmlStyle?.["--shiki-dark"] as string | undefined,
    })),
  );
}
