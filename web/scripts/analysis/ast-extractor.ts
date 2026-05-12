/**
 * ts-morph AST extractor for React components and hook call sites.
 * Mirrors the role of src/analysis/ast_extractor.py for the frontend.
 */
import path from "node:path";
import {
  Node,
  Project,
  SourceFile,
  SyntaxKind,
  type CallExpression,
  type FunctionDeclaration,
  type ArrowFunction,
  type FunctionExpression,
} from "ts-morph";

export interface ComponentInfo {
  name: string;
  file: string;
  line: number;
  propsTypeName: string | null;
}

export interface HookCallInfo {
  hookName: string;
  /** enclosing component or function name */
  callerName: string;
  file: string;
  line: number;
  /** true when the call is inside a conditional branch or loop */
  isConditional: boolean;
  /** dependency array literal text, if present (useEffect / useCallback / useMemo) */
  depsArrayText: string | null;
}

// ─── helpers ────────────────────────────────────────────────────────────────

const HOOK_PREFIX = /^use[A-Z]/;
const DEPS_HOOKS = new Set(["useEffect", "useCallback", "useMemo", "useLayoutEffect"]);

function isInsideConditional(node: Node): boolean {
  let cur: Node | undefined = node.getParent();
  while (cur) {
    const kind = cur.getKind();
    if (
      kind === SyntaxKind.IfStatement ||
      kind === SyntaxKind.ConditionalExpression ||
      kind === SyntaxKind.WhileStatement ||
      kind === SyntaxKind.ForStatement ||
      kind === SyntaxKind.ForOfStatement ||
      kind === SyntaxKind.ForInStatement ||
      kind === SyntaxKind.SwitchStatement
    ) {
      return true;
    }
    // Stop at the enclosing function boundary
    if (
      kind === SyntaxKind.FunctionDeclaration ||
      kind === SyntaxKind.ArrowFunction ||
      kind === SyntaxKind.FunctionExpression ||
      kind === SyntaxKind.MethodDeclaration
    ) {
      break;
    }
    cur = cur.getParent();
  }
  return false;
}

function enclosingFunctionName(node: Node): string {
  let cur: Node | undefined = node.getParent();
  while (cur) {
    if (Node.isFunctionDeclaration(cur)) {
      return (cur as FunctionDeclaration).getName() ?? "<anonymous>";
    }
    if (Node.isVariableDeclaration(cur)) {
      return cur.getName();
    }
    cur = cur.getParent();
  }
  return "<module>";
}

function propsTypeName(fn: FunctionDeclaration | ArrowFunction | FunctionExpression): string | null {
  const params = fn.getParameters();
  if (params.length === 0) return null;
  const typeNode = params[0].getTypeNode();
  return typeNode ? typeNode.getText() : null;
}

function isComponentName(name: string): boolean {
  return /^[A-Z]/.test(name);
}

// ─── per-file extraction ─────────────────────────────────────────────────────

function extractFromFile(sf: SourceFile): { components: ComponentInfo[]; hookCalls: HookCallInfo[] } {
  const components: ComponentInfo[] = [];
  const hookCalls: HookCallInfo[] = [];
  const filePath = sf.getFilePath();

  // Named function declarations that look like components
  for (const fn of sf.getFunctions()) {
    const name = fn.getName();
    if (name && isComponentName(name)) {
      components.push({
        name,
        file: filePath,
        line: fn.getStartLineNumber(),
        propsTypeName: propsTypeName(fn),
      });
    }
  }

  // Arrow-function / function-expression variable declarations (const Foo = () => ...)
  for (const vd of sf.getVariableDeclarations()) {
    const name = vd.getName();
    if (!isComponentName(name)) continue;
    const init = vd.getInitializer();
    if (!init) continue;
    if (Node.isArrowFunction(init) || Node.isFunctionExpression(init)) {
      components.push({
        name,
        file: filePath,
        line: vd.getStartLineNumber(),
        propsTypeName: propsTypeName(init as ArrowFunction | FunctionExpression),
      });
    }
  }

  // All call expressions — collect hook calls
  sf.forEachDescendant((node) => {
    if (!Node.isCallExpression(node)) return;
    const call = node as CallExpression;
    const expr = call.getExpression();
    if (!Node.isIdentifier(expr)) return;
    const hookName = expr.getText();
    if (!HOOK_PREFIX.test(hookName)) return;

    let depsArrayText: string | null = null;
    if (DEPS_HOOKS.has(hookName)) {
      // deps array is the last argument when it's an array literal
      const args = call.getArguments();
      const last = args[args.length - 1];
      if (last && Node.isArrayLiteralExpression(last)) {
        depsArrayText = last.getText();
      }
    }

    hookCalls.push({
      hookName,
      callerName: enclosingFunctionName(node),
      file: filePath,
      line: node.getStartLineNumber(),
      isConditional: isInsideConditional(node),
      depsArrayText,
    });
  });

  return { components, hookCalls };
}

// ─── public API ──────────────────────────────────────────────────────────────

export interface ExtractionResult {
  components: ComponentInfo[];
  hookCalls: HookCallInfo[];
}

export function extractFromProject(srcDir: string): ExtractionResult {
  // tsconfig.json lives at web/tsconfig.json — one level above web/src
  const tsConfigFilePath = path.resolve(srcDir, "..", "tsconfig.json");
  const project = new Project({
    tsConfigFilePath,
    skipAddingFilesFromTsConfig: false,
  });

  const allComponents: ComponentInfo[] = [];
  const allHookCalls: HookCallInfo[] = [];

  for (const sf of project.getSourceFiles()) {
    // Only analyse files under the target srcDir
    if (!sf.getFilePath().startsWith(srcDir)) continue;
    const { components, hookCalls } = extractFromFile(sf);
    allComponents.push(...components);
    allHookCalls.push(...hookCalls);
  }

  return { components: allComponents, hookCalls: allHookCalls };
}
