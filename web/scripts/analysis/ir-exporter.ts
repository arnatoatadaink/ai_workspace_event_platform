/**
 * Frontend IR exporter: runs static analysis on web/src and writes
 * runtime/frontend_analysis.json for the Python IR builder to consume.
 *
 * Run via: pnpm analyze:ir
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { extractFromProject } from "./ast-extractor.js";
import { extractFetchCalls } from "./fetch-extractor.js";

// ─── path resolution ──────────────────────────────────────────────────────────

const SCRIPT_DIR = path.dirname(new URL(import.meta.url).pathname);
const WEB_DIR = path.resolve(SCRIPT_DIR, "../..");
const SRC_DIR = path.resolve(WEB_DIR, "src");
const PROJECT_ROOT = path.resolve(WEB_DIR, "..");
const OUTPUT_PATH = path.resolve(PROJECT_ROOT, "runtime/frontend_analysis.json");

// ─── IR types (mirror of src/analysis/ir_builder.py) ─────────────────────────

interface IRNode {
  id: string;
  kind: "component" | "hook" | "fetch_call" | "function";
  label: string;
  meta: Record<string, unknown>;
}

interface IREdge {
  source: string;
  target: string;
  kind: "uses_hook" | "calls";
  label?: string;
}

interface FrontendAnalysis {
  nodes: IRNode[];
  edges: IREdge[];
}

// ─── main ─────────────────────────────────────────────────────────────────────

function run(): void {
  console.log(`Extracting frontend IR from ${SRC_DIR} …`);

  const { components, hookCalls } = extractFromProject(SRC_DIR);
  const { fetchCalls } = extractFetchCalls(SRC_DIR);

  const nodes: IRNode[] = [];
  const edges: IREdge[] = [];
  const nodeIds = new Set<string>();

  function addNode(node: IRNode): void {
    if (!nodeIds.has(node.id)) {
      nodes.push(node);
      nodeIds.add(node.id);
    }
  }

  // Component nodes
  for (const comp of components) {
    addNode({
      id: `fe:component:${comp.name}`,
      kind: "component",
      label: comp.name,
      meta: { file: comp.file, line: comp.line, propsTypeName: comp.propsTypeName },
    });
  }

  // Hook call nodes + uses_hook edges
  const componentNames = new Set(components.map((c) => c.name));
  for (const hook of hookCalls) {
    const hookNodeId = `fe:hook:${hook.hookName}@${hook.callerName}`;
    addNode({
      id: hookNodeId,
      kind: "hook",
      label: `${hook.hookName} (${hook.callerName})`,
      meta: {
        hookName: hook.hookName,
        callerName: hook.callerName,
        file: hook.file,
        line: hook.line,
        isConditional: hook.isConditional,
        depsArrayText: hook.depsArrayText,
      },
    });

    // Only emit edges from known components to their hooks
    if (componentNames.has(hook.callerName)) {
      edges.push({
        source: `fe:component:${hook.callerName}`,
        target: hookNodeId,
        kind: "uses_hook",
      });
    }
  }

  // Fetch call nodes + caller → fetch edges
  const seenCallerFetchPairs = new Set<string>();
  for (const fetchCall of fetchCalls) {
    const fetchId = `fe:fetch:${fetchCall.method}:${fetchCall.path}`;
    addNode({
      id: fetchId,
      kind: "fetch_call",
      label: `${fetchCall.method} ${fetchCall.path}`,
      meta: {
        method: fetchCall.method,
        path: fetchCall.path,
        callerName: fetchCall.callerName,
        file: fetchCall.file,
        line: fetchCall.line,
      },
    });

    const { callerName } = fetchCall;
    if (callerName === "<module>" || callerName === "<anonymous>") continue;

    let callerNodeId: string;
    if (componentNames.has(callerName)) {
      callerNodeId = `fe:component:${callerName}`;
    } else {
      // API utility function (e.g. fetchIR, getSessionStats)
      callerNodeId = `fe:function:${callerName}`;
      addNode({
        id: callerNodeId,
        kind: "function",
        label: callerName,
        meta: { file: fetchCall.file, line: fetchCall.line },
      });
    }

    const edgeKey = `${callerNodeId}→${fetchId}`;
    if (!seenCallerFetchPairs.has(edgeKey)) {
      seenCallerFetchPairs.add(edgeKey);
      edges.push({ source: callerNodeId, target: fetchId, kind: "calls" });
    }
  }

  const output: FrontendAnalysis = { nodes, edges };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output, null, 2), "utf-8");

  console.log(
    `Wrote ${nodes.length} nodes (${components.length} components, ` +
    `${hookCalls.length} hooks, ${fetchCalls.length} fetches), ` +
    `${edges.length} edges → ${OUTPUT_PATH}`,
  );
}

run();
