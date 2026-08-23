/**
 * Minimal token-based syntax highlighter. Zero dependencies.
 *
 * Goal: make code in citations readable, not produce a full Prism-grade
 * highlighter. We classify each line into segments and wrap them in
 * <span class="tk-*"> for CSS to colour. No regex backreferences, no
 * catastrophic-backtracking traps.
 *
 * The language map covers everything in `ALLOWED_EXTENSIONS` from the
 * backend ingestion module so a citation is highlighted regardless of
 * which source file produced it.
 */

import { escapeHTML } from "./markdown";

type Segment = { kind: TK; text: string };
type TK =
  | "kw"
  | "str"
  | "num"
  | "com"
  | "fn"
  | "type"
  | "attr"
  | "tag"
  | "op"
  | "punct"
  | "plain";

interface LangSpec {
  keywords: Set<string>;
  types: Set<string>;
  lineComment?: RegExp;
  blockComment?: { start: RegExp; end: RegExp };
  stringRules: Array<{ start: RegExp; end: RegExp | string; escape?: RegExp }>;
  numberRule: RegExp;
  identifierRule: RegExp;
}

function setFrom(...words: string[]): Set<string> {
  return new Set(words);
}

const LANG_SPECS: Record<string, LangSpec> = {
  py: {
    keywords: setFrom(
      "False", "None", "True", "and", "as", "assert", "async", "await", "break",
      "class", "continue", "def", "del", "elif", "else", "except", "finally",
      "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
      "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
      "match", "case",
    ),
    types: setFrom(
      "int", "float", "str", "bool", "list", "dict", "tuple", "set", "bytes",
      "object", "type", "Optional", "Any", "Union", "List", "Dict", "Tuple",
      "Set",
    ),
    lineComment: /#.*$/,
    stringRules: [
      { start: /"""/, end: /"""/, escape: /\\./ },
      { start: /'''/, end: /'''/, escape: /\\./ },
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/, escape: /\\./ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  js: {
    keywords: setFrom(
      "async", "await", "break", "case", "catch", "class", "const", "continue",
      "debugger", "default", "delete", "do", "else", "export", "extends",
      "finally", "for", "from", "function", "if", "import", "in", "instanceof",
      "let", "new", "of", "return", "static", "super", "switch", "this",
      "throw", "try", "typeof", "var", "void", "while", "with", "yield",
    ),
    types: setFrom(
      "Array", "Boolean", "Date", "Error", "Function", "JSON", "Map", "Math",
      "Number", "Object", "Promise", "RegExp", "Set", "String", "Symbol",
      "undefined", "null", "true", "false",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [
      { start: /`/, end: /`/, escape: /\\./ },
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/, escape: /\\./ },
    ],
    numberRule: /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/,
    identifierRule: /[A-Za-z_$][A-Za-z0-9_$]*/,
  },
  // ts shares js's syntax; tsx/jsx add angle-bracket tag handling at render time.
  ts: null as unknown as LangSpec,
  tsx: null as unknown as LangSpec,
  jsx: null as unknown as LangSpec,
  go: {
    keywords: setFrom(
      "break", "case", "chan", "const", "continue", "default", "defer", "else",
      "fallthrough", "for", "func", "go", "goto", "if", "import", "interface",
      "map", "package", "range", "return", "select", "struct", "switch", "type",
      "var",
    ),
    types: setFrom(
      "bool", "byte", "complex64", "complex128", "error", "float32", "float64",
      "int", "int8", "int16", "int32", "int64", "rune", "string", "uint",
      "uint8", "uint16", "uint32", "uint64", "uintptr", "true", "false", "nil",
      "any",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /`/, end: /`/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  rs: {
    keywords: setFrom(
      "as", "async", "await", "break", "const", "continue", "crate", "dyn",
      "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in", "let",
      "loop", "match", "mod", "move", "mut", "pub", "ref", "return", "self",
      "Self", "static", "struct", "super", "trait", "true", "type", "unsafe",
      "use", "where", "while",
    ),
    types: setFrom(
      "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64",
      "u128", "usize", "f32", "f64", "bool", "char", "str", "String", "Vec",
      "Option", "Result",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  java: {
    keywords: setFrom(
      "abstract", "assert", "break", "case", "catch", "class", "const",
      "continue", "default", "do", "else", "enum", "extends", "final",
      "finally", "for", "goto", "if", "implements", "import", "instanceof",
      "interface", "native", "new", "package", "private", "protected", "public",
      "return", "static", "strictfp", "super", "switch", "synchronized", "this",
      "throw", "throws", "transient", "try", "void", "volatile", "while",
    ),
    types: setFrom(
      "boolean", "byte", "char", "double", "float", "int", "long", "short",
      "String", "Object", "Integer", "Boolean", "List", "Map", "Set",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?(?:[fFdDlL])?\b/,
    identifierRule: /[A-Za-z_$][A-Za-z0-9_$]*/,
  },
  kt: {
    keywords: setFrom(
      "abstract", "actual", "also", "annotation", "as", "break", "by", "catch",
      "class", "companion", "const", "constructor", "continue", "data", "do",
      "else", "enum", "expect", "external", "false", "final", "finally", "for",
      "fun", "get", "if", "import", "in", "infix", "init", "inline",
      "inner", "interface", "internal", "is", "lateinit", "noinline", "null",
      "object", "open", "operator", "out", "override", "package", "private",
      "protected", "public", "reified", "return", "sealed", "set", "super",
      "suspend", "tailrec", "this", "throw", "true", "try", "typealias", "val",
      "var", "vararg", "when", "where", "while",
    ),
    types: setFrom(
      "Int", "Long", "Float", "Double", "Boolean", "String", "Char", "Any",
      "Unit", "List", "Map", "Set", "Array",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [
      { start: /"""/, end: /"""/ },
      { start: /"/, end: /"/, escape: /\\./ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  rb: {
    keywords: setFrom(
      "BEGIN", "END", "alias", "and", "begin", "break", "case", "class", "def",
      "defined?", "do", "else", "elsif", "end", "ensure", "false", "for", "if",
      "in", "module", "next", "nil", "not", "or", "redo", "rescue", "retry",
      "return", "self", "super", "then", "true", "undef", "unless", "until",
      "when", "while", "yield",
    ),
    types: setFrom("Array", "Hash", "String", "Symbol", "Integer", "Float", "Object"),
    lineComment: /#.*$/,
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*[?!]?/,
  },
  php: {
    keywords: setFrom(
      "abstract", "and", "array", "as", "break", "callable", "case", "catch",
      "class", "clone", "const", "continue", "declare", "default", "die", "do",
      "echo", "else", "elseif", "empty", "enddeclare", "endfor", "endforeach",
      "endif", "endswitch", "endwhile", "eval", "exit", "extends", "false",
      "final", "finally", "for", "foreach", "function", "global", "goto", "if",
      "implements", "include", "include_once", "instanceof", "insteadof",
      "interface", "isset", "list", "namespace", "new", "null", "or", "print",
      "private", "protected", "public", "require", "require_once", "return",
      "static", "switch", "throw", "trait", "true", "try", "unset", "use",
      "var", "while", "xor", "yield",
    ),
    types: setFrom("int", "string", "array", "float", "bool", "object", "void", "mixed"),
    lineComment: /\/\/.*$|#[^\[!].*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /\$[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*/,
  },
  cs: {
    keywords: setFrom(
      "abstract", "as", "base", "break", "case", "catch", "checked", "class",
      "const", "continue", "default", "delegate", "do", "else", "enum", "event",
      "explicit", "extern", "false", "finally", "fixed", "for", "foreach", "goto",
      "if", "implicit", "in", "interface", "internal", "is", "lock", "namespace",
      "new", "null", "operator", "out", "override", "params", "private",
      "protected", "public", "readonly", "ref", "return", "sealed", "sizeof",
      "stackalloc", "static", "struct", "switch", "this", "throw", "true", "try",
      "typeof", "unchecked", "unsafe", "using", "var", "virtual", "void",
      "volatile", "while",
    ),
    types: setFrom(
      "bool", "byte", "char", "decimal", "double", "float", "int", "long",
      "object", "sbyte", "short", "string", "uint", "ulong", "ushort", "void",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /@"/, end: /"/, escape: /""/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?(?:[fFdDmM])?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  cpp: cppSpec(),
  c: cppSpec(),
  cc: cppSpec(),
  cxx: cppSpec(),
  hpp: cppSpec(),
  hxx: cppSpec(),
  h: cppSpec(),
  swift: {
    keywords: setFrom(
      "associatedtype", "class", "deinit", "enum", "extension", "fileprivate",
      "func", "import", "init", "inout", "internal", "let", "open", "operator",
      "private", "protocol", "public", "rethrows", "return", "static", "struct",
      "subscript", "typealias", "var", "break", "case", "continue", "default",
      "defer", "do", "else", "fallthrough", "for", "guard", "if", "in", "repeat",
      "switch", "where", "while", "as", "catch", "throw", "throws", "try",
      "true", "false", "nil", "async", "await", "actor",
    ),
    types: setFrom("Int", "Double", "Float", "String", "Bool", "Array", "Dictionary", "Set", "Optional"),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  scala: {
    keywords: setFrom(
      "abstract", "case", "catch", "class", "def", "do", "else", "extends",
      "false", "final", "finally", "for", "forSome", "if", "implicit", "import",
      "lazy", "match", "new", "null", "object", "override", "package", "private",
      "protected", "return", "sealed", "super", "this", "throw", "trait", "try",
      "true", "type", "val", "var", "while", "with", "yield",
    ),
    types: setFrom("Int", "Long", "Double", "Float", "Boolean", "String", "Any", "Nothing", "List", "Map", "Set"),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  sh: shellSpec(),
  bash: shellSpec(),
  zsh: shellSpec(),
  sql: {
    keywords: setFrom(
      "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
      "ON", "GROUP", "BY", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET", "HAVING",
      "AS", "AND", "OR", "NOT", "NULL", "IS", "IN", "EXISTS", "INSERT", "INTO",
      "VALUES", "UPDATE", "SET", "DELETE", "CREATE", "TABLE", "DROP", "ALTER",
      "ADD", "COLUMN", "INDEX", "VIEW", "DISTINCT", "UNION", "ALL", "CASE",
      "WHEN", "THEN", "ELSE", "END", "WITH", "RECURSIVE", "TRUE", "FALSE",
      "select", "from", "where", "join", "inner", "left", "right", "outer",
      "on", "group", "by", "order", "asc", "desc", "limit", "offset", "having",
      "as", "and", "or", "not", "null", "is", "in", "exists", "insert", "into",
      "values", "update", "set", "delete", "create", "table", "drop", "alter",
      "add", "column", "index", "view", "distinct", "union", "all", "case",
      "when", "then", "else", "end", "with", "recursive", "true", "false",
    ),
    types: setFrom(
      "INT", "INTEGER", "BIGINT", "SMALLINT", "VARCHAR", "TEXT", "CHAR",
      "BOOLEAN", "DATE", "TIMESTAMP", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL",
      "int", "integer", "bigint", "smallint", "varchar", "text", "char",
      "boolean", "date", "timestamp", "float", "double", "numeric", "decimal",
    ),
    lineComment: /--.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /'/, end: /'/ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  html: htmlSpec(),
  htm: htmlSpec(),
  xml: htmlSpec(),
  css: cssSpec(),
  scss: cssSpec(),
  less: cssSpec(),
  yaml: cssSpec(),
  yml: cssSpec(),
  toml: cssSpec(),
  json: jsonSpec(),
  ini: iniSpec(),
  cfg: iniSpec(),
  dockerfile: dockerSpec(),
  proto: {
    keywords: setFrom(
      "syntax", "import", "package", "option", "message", "enum", "service",
      "rpc", "returns", "stream", "extend", "extensions", "reserved", "repeated",
      "optional", "required", "oneof", "map",
    ),
    types: setFrom(
      "double", "float", "int32", "int64", "uint32", "uint64", "sint32",
      "sint64", "fixed32", "fixed64", "sfixed32", "sfixed64", "bool", "string",
      "bytes",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  lua: {
    keywords: setFrom(
      "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
      "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return",
      "then", "true", "until", "while",
    ),
    types: setFrom(),
    lineComment: /--.*$/,
    blockComment: { start: /--\[\[/, end: /\]\]/ },
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  },
  ex: {
    keywords: setFrom(
      "def", "defmodule", "defmacro", "defp", "do", "end", "fn", "case", "cond",
      "if", "unless", "for", "while", "with", "receive", "try", "after", "rescue",
      "raise", "throw", "alias", "require", "import", "use", "true", "false",
      "nil", "when",
    ),
    types: setFrom(
      "atom", "binary", "bitstring", "boolean", "charlist", "float", "function",
      "integer", "list", "map", "nil", "pid", "port", "reference", "tuple",
    ),
    lineComment: /#.*$/,
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*[?!]?/,
  },
  exs: null as unknown as LangSpec,
  vue: htmlSpec(),
  svelte: htmlSpec(),
  md: htmlSpec(),
  mdx: htmlSpec(),
  rst: htmlSpec(),
  txt: null as unknown as LangSpec,
  m: cppSpec(),
  mm: cppSpec(),
};

function cppSpec(): LangSpec {
  return {
    keywords: setFrom(
      "alignas", "alignof", "and", "auto", "bool", "break", "case", "catch",
      "char", "class", "const", "constexpr", "continue", "decltype", "default",
      "delete", "do", "double", "else", "enum", "explicit", "export", "extern",
      "false", "float", "for", "friend", "goto", "if", "inline", "int", "long",
      "mutable", "namespace", "new", "noexcept", "nullptr", "operator", "or",
      "private", "protected", "public", "register", "return", "short", "signed",
      "sizeof", "static", "struct", "switch", "template", "this", "throw", "true",
      "try", "typedef", "typeid", "typename", "union", "unsigned", "using",
      "virtual", "void", "volatile", "while",
    ),
    types: setFrom(
      "size_t", "ssize_t", "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t",
      "uint16_t", "uint32_t", "uint64_t", "string", "vector", "map", "set",
      "pair", "tuple", "unique_ptr", "shared_ptr", "weak_ptr",
    ),
    lineComment: /\/\/.*$/,
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /\b\d+(?:\.\d+)?(?:[fFuUlL])?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  };
}

function shellSpec(): LangSpec {
  return {
    keywords: setFrom(
      "if", "then", "else", "elif", "fi", "case", "esac", "for", "while",
      "until", "do", "done", "function", "return", "in", "break", "continue",
      "export", "local", "readonly", "declare", "unset", "source", "alias",
    ),
    types: setFrom(),
    lineComment: /#.*$/,
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  };
}

function htmlSpec(): LangSpec {
  return {
    keywords: setFrom(),
    types: setFrom(),
    lineComment: /<!--.*?-->/,
    blockComment: { start: /<!--/, end: /-->/ },
    stringRules: [
      { start: /"/, end: /"/ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_-]*/,
  };
}

function cssSpec(): LangSpec {
  return {
    keywords: setFrom(
      "important", "inherit", "initial", "unset", "revert", "auto", "none",
    ),
    types: setFrom(),
    blockComment: { start: /\/\*/, end: /\*\// },
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/, escape: /\\./ },
    ],
    numberRule: /-?\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|ch|ex|pt|pc|in|cm|mm)?/,
    identifierRule: /[A-Za-z_-][A-Za-z0-9_-]*/,
  };
}

function jsonSpec(): LangSpec {
  return {
    keywords: setFrom("true", "false", "null"),
    types: setFrom(),
    stringRules: [{ start: /"/, end: /"/, escape: /\\./ }],
    numberRule: /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  };
}

function iniSpec(): LangSpec {
  return {
    keywords: setFrom("true", "false", "yes", "no", "on", "off"),
    types: setFrom(),
    lineComment: /[#;].*$/,
    stringRules: [
      { start: /"/, end: /"/ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+(?:\.\d+)?\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_-]*/,
  };
}

function dockerSpec(): LangSpec {
  return {
    keywords: setFrom(
      "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD",
      "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD",
      "STOPSIGNAL", "HEALTHCHECK", "SHELL", "AS", "from", "run", "cmd",
      "label", "maintainer", "expose", "env", "add", "copy", "entrypoint",
      "volume", "user", "workdir", "arg", "onbuild", "stopsignal",
      "healthcheck", "shell", "as",
    ),
    types: setFrom(),
    lineComment: /#.*$/,
    stringRules: [
      { start: /"/, end: /"/, escape: /\\./ },
      { start: /'/, end: /'/ },
    ],
    numberRule: /\b\d+\b/,
    identifierRule: /[A-Za-z_][A-Za-z0-9_]*/,
  };
}

// Fill aliases for languages that share a spec.
LANG_SPECS.ts = LANG_SPECS.js;
LANG_SPECS.tsx = LANG_SPECS.js;
LANG_SPECS.jsx = LANG_SPECS.js;
LANG_SPECS.exs = LANG_SPECS.ex;

/**
 * Highlight one line of source code. Returns an HTML string of <span> tokens.
 * Pure presentation — caller is responsible for escaping the wrapping <pre>.
 */
export function highlightLine(line: string, lang: string | null): string {
  const spec = lang ? LANG_SPECS[lang] : null;
  if (!spec) return escapeHTML(line);

  const segs = tokenize(line, spec);
  return segs
    .map((s) =>
      s.kind === "plain"
        ? escapeHTML(s.text)
        : `<span class="tk-${s.kind}">${escapeHTML(s.text)}</span>`,
    )
    .join("");
}

function tokenize(line: string, spec: LangSpec): Segment[] {
  const out: Segment[] = [];
  let i = 0;
  const n = line.length;

  const tryMatch = (re: RegExp, from: number): RegExpExecArray | null => {
    re.lastIndex = from;
    const m = re.exec(line);
    re.lastIndex = 0;
    return m;
  };

  while (i < n) {
    const rest = line.slice(i);

    // Line comment
    if (spec.lineComment) {
      const m = rest.match(spec.lineComment);
      if (m && m.index === 0) {
        out.push({ kind: "com", text: m[0] });
        i += m[0].length;
        continue;
      }
    }

    // Strings
    let matchedString = false;
    for (const r of spec.stringRules) {
      if (rest.startsWith(r.start.source.charAt(0)) === false && !r.start.test(rest[0] || "")) {
        // cheap heuristic: test the literal start char
      }
      const start = r.start.source;
      const ch = start.charAt(0);
      if (rest.startsWith(ch)) {
        const remaining = line.slice(i);
        const endSrc = typeof r.end === "string" ? r.end : r.end.source;
        const endChar = endSrc.charAt(0);
        let j = 1;
        while (j < remaining.length) {
          if (remaining[j] === "\\" && r.escape) {
            j += 2;
            continue;
          }
          if (remaining[j] === endChar) {
            j += 1;
            break;
          }
          j += 1;
        }
        out.push({ kind: "str", text: remaining.slice(0, j) });
        i += j;
        matchedString = true;
        break;
      }
    }
    if (matchedString) continue;

    // Number
    const numMatch = tryMatch(spec.numberRule, i);
    if (numMatch && numMatch.index === i) {
      out.push({ kind: "num", text: numMatch[0] });
      i += numMatch[0].length;
      continue;
    }

    // Identifier / keyword / type
    const idMatch = tryMatch(spec.identifierRule, i);
    if (idMatch && idMatch.index === i) {
      const word = idMatch[0];
      let kind: TK = "plain";
      if (spec.keywords.has(word)) kind = "kw";
      else if (spec.types.has(word)) kind = "type";
      else if (/^[A-Z]/.test(word) && /[a-z]/.test(word)) kind = "type";
      out.push({ kind, text: word });
      i += word.length;
      continue;
    }

    // Function call detection: identifier followed by (
    if (
      out.length > 0 &&
      out[out.length - 1].kind === "plain" &&
      line[i] === "(" &&
      /\w$/.test(out[out.length - 1].text)
    ) {
      const last = out.pop()!;
      out.push({ kind: "fn", text: last.text });
      out.push({ kind: "punct", text: "(" });
      i += 1;
      continue;
    }

    // Punctuation / operators
    const ch = line[i];
    if (/[{}\[\]()(),;:]/.test(ch)) {
      out.push({ kind: "punct", text: ch });
      i += 1;
      continue;
    }
    if (/[+\-*/%=<>!&|^~?]/.test(ch)) {
      out.push({ kind: "op", text: ch });
      i += 1;
      continue;
    }

    // Fallback: a single char.
    out.push({ kind: "plain", text: ch });
    i += 1;
  }

  return out;
}

/**
 * Highlight a multi-line code block. Preserves the trailing newline shape
 * so <pre> wrapping renders identically to the unhighlighted version.
 */
export function highlightCode(content: string, lang: string | null): string {
  if (!lang || !LANG_SPECS[lang]) return escapeHTML(content);
  const lines = content.split("\n");
  const out: string[] = [];
  for (let i = 0; i < lines.length; i += 1) {
    out.push(highlightLine(lines[i], lang));
  }
  return out.join("\n");
}
