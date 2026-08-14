/** Real temp projects written to disk — the analysis tests never mock ts-morph or the FS. */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const roots: string[] = [];

export function makeProject(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "tempest-ts-sidecar-"));
  roots.push(root);
  for (const [relPath, content] of Object.entries(files)) {
    const abs = join(root, relPath);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, content, "utf8");
  }
  return root;
}

export function cleanupProjects(): void {
  while (roots.length > 0) {
    const root = roots.pop();
    if (root !== undefined) {
      rmSync(root, { recursive: true, force: true });
    }
  }
}

export function allLines(source: string): number[] {
  return Array.from({ length: source.split("\n").length }, (_, i) => i + 1);
}
