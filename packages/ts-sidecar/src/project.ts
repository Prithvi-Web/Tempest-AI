/**
 * ts-morph project loading. If the analyzed repo has a `tsconfig.json` at its root we load it —
 * that is what makes path aliases (`compilerOptions.paths`) and project settings resolve. With no
 * tsconfig we fall back to an ad-hoc project over just the requested files.
 */
import { existsSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";

import { Project, type SourceFile, ts } from "ts-morph";

import { INVALID_PARAMS, RpcError } from "./rpc.ts";

export function loadProject(projectRoot: string, files: readonly string[]): Project {
  if (!existsSync(projectRoot)) {
    throw new RpcError(INVALID_PARAMS, `projectRoot does not exist: ${projectRoot}`);
  }
  const tsConfigFilePath = join(projectRoot, "tsconfig.json");
  const project = existsSync(tsConfigFilePath)
    ? new Project({ tsConfigFilePath })
    : new Project({
        compilerOptions: {
          allowJs: true,
          strict: true,
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ESNext,
          moduleResolution: ts.ModuleResolutionKind.Bundler,
        },
      });
  for (const file of files) {
    const abs = absolutePath(projectRoot, file);
    if (!existsSync(abs)) {
      throw new RpcError(INVALID_PARAMS, `file not found: ${abs}`);
    }
    if (project.getSourceFile(abs) === undefined) {
      project.addSourceFileAtPath(abs);
    }
  }
  return project;
}

export function absolutePath(projectRoot: string, file: string): string {
  return isAbsolute(file) ? file : join(projectRoot, file);
}

/** Repo-relative POSIX path — the canonical `filePath` in every response. */
export function relativePosixPath(projectRoot: string, sourceFile: SourceFile): string {
  return relative(projectRoot, sourceFile.getFilePath()).split(sep).join("/");
}
