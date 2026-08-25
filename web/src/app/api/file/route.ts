/**
 * File contents, highlighted on the server.
 *
 * The code pane switches files without a page load, so highlighting
 * cannot live in a server component. This route keeps Shiki on the
 * server anyway: the browser receives tokens, never the highlighter.
 */

import { NextResponse } from "next/server";

import { fetchFile } from "@/lib/api";
import { highlight } from "@/lib/highlight";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const owner = params.get("owner");
  const name = params.get("name");
  const path = params.get("path");

  if (!owner || !name || !path) {
    return NextResponse.json(
      { error: "owner, name and path are required" },
      { status: 400 },
    );
  }

  try {
    const file = await fetchFile(owner, name, path);
    return NextResponse.json({
      path: file.path,
      lines: await highlight(file.content, file.path),
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 404 },
    );
  }
}
