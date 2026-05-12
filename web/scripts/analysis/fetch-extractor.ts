/**
 * Extracts fetch() call sites from TypeScript source files.
 * Mirrors the SQL query extraction role for the frontend API layer.
 */
import path from "node:path";
import {
  Node,
  Project,
  SyntaxKind,
  type CallExpression,
  type NoSubstitutionTemplateLiteral,
  type TemplateExpression,
} from "ts-morph";

export interface FetchCallInfo {
  /** HTTP method, uppercased (defaults to "GET") */
  method: string;
  /** Normalized URL path: BASE prefix stripped, template vars replaced with {*} */
  path: string;
  /** Enclosing component or function name */
  callerName: string;
  file: string;
  line: number;
}

// ─── helpers ──────────────────────────────────────────────────────────────────

const BASE_PLACEHOLDER = "${BASE}";
const TEMPLATE_VAR_RE = /\$\{[^}]+\}/g;
const ORIGIN_RE = /^https?:\/\/[^/]+/;

function stripOrigin(raw: string): string {
  if (raw.startsWith(BASE_PLACEHOLDER)) {
    return raw.slice(BASE_PLACEHOLDER.length);
  }
  return raw.replace(ORIGIN_RE, "");
}

function normalizePath(raw: string): string {
  return stripOrigin(raw).replace(TEMPLATE_VAR_RE, "{*}");
}

function enclosingFunctionName(node: Node): string {
  let cur: Node | undefined = node.getParent();
  while (cur) {
    if (Node.isFunctionDeclaration(cur)) return cur.getName() ?? "<anonymous>";
    if (Node.isVariableDeclaration(cur)) return cur.getName();
    if (Node.isMethodDeclaration(cur)) return cur.getName();
    cur = cur.getParent();
  }
  return "<module>";
}

function extractUrlFromArg(arg: Node): string | null {
  // Plain string literal
  if (Node.isStringLiteral(arg)) {
    return normalizePath(arg.getLiteralValue());
  }

  // No-substitution template literal: `${BASE}/static`
  if (arg.getKind() === SyntaxKind.NoSubstitutionTemplateLiteral) {
    const lit = arg as NoSubstitutionTemplateLiteral;
    return normalizePath(lit.getLiteralText());
  }

  // Template expression: `${BASE}/path/${id}`
  if (Node.isTemplateExpression(arg)) {
    const te = arg as TemplateExpression;
    const head = te.getHead().getLiteralText();
    const tail = te
      .getTemplateSpans()
      .map((span) => "${" + span.getExpression().getText() + "}" + span.getLiteral().getLiteralText())
      .join("");
    return normalizePath(head + tail);
  }

  return null;
}

function extractMethodFromOptions(options: Node | undefined): string {
  if (!options || !Node.isObjectLiteralExpression(options)) return "GET";
  for (const prop of options.getProperties()) {
    if (!Node.isPropertyAssignment(prop) || prop.getName() !== "method") continue;
    const init = prop.getInitializer();
    if (init && Node.isStringLiteral(init)) {
      return init.getLiteralValue().toUpperCase();
    }
  }
  return "GET";
}

function extractFromFile(sf: ReturnType<Project["getSourceFiles"]>[number]): FetchCallInfo[] {
  const results: FetchCallInfo[] = [];
  const filePath = sf.getFilePath();

  sf.forEachDescendant((node) => {
    if (!Node.isCallExpression(node)) return;
    const call = node as CallExpression;
    const expr = call.getExpression();
    if (!Node.isIdentifier(expr) || expr.getText() !== "fetch") return;

    const args = call.getArguments();
    if (args.length === 0) return;

    const urlPath = extractUrlFromArg(args[0]);
    if (!urlPath) return;

    results.push({
      method: extractMethodFromOptions(args[1]),
      path: urlPath,
      callerName: enclosingFunctionName(node),
      file: filePath,
      line: node.getStartLineNumber(),
    });
  });

  return results;
}

// ─── public API ───────────────────────────────────────────────────────────────

export interface FetchExtractionResult {
  fetchCalls: FetchCallInfo[];
}

export function extractFetchCalls(srcDir: string): FetchExtractionResult {
  const tsConfigFilePath = path.resolve(srcDir, "..", "tsconfig.json");
  const project = new Project({
    tsConfigFilePath,
    skipAddingFilesFromTsConfig: false,
  });

  const allCalls: FetchCallInfo[] = [];
  for (const sf of project.getSourceFiles()) {
    if (!sf.getFilePath().startsWith(srcDir)) continue;
    allCalls.push(...extractFromFile(sf));
  }
  return { fetchCalls: allCalls };
}
