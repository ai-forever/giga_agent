export interface CodeToken {
  text: string;
  color: string;
}

export const PY_COLORS = {
  keyword: "0000CC",
  builtin: "008080",
  string: "008000",
  comment: "808080",
  number: "B85C00",
  decorator: "AA22FF",
  default: "333333",
};

const PY_KEYWORDS = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);

const PY_BUILTINS = new Set([
  "print",
  "len",
  "range",
  "int",
  "str",
  "float",
  "list",
  "dict",
  "set",
  "tuple",
  "bool",
  "type",
  "isinstance",
  "enumerate",
  "zip",
  "map",
  "filter",
  "sorted",
  "reversed",
  "open",
  "super",
  "property",
  "staticmethod",
  "classmethod",
  "input",
  "abs",
  "max",
  "min",
  "sum",
  "any",
  "all",
  "hasattr",
  "getattr",
  "setattr",
  "ValueError",
  "TypeError",
  "KeyError",
  "IndexError",
  "Exception",
  "self",
]);

const PY_TOKEN_RE = new RegExp(
  [
    "([fFrRbBuU]{0,2}(?:\"{3}[\\s\\S]*?(?:\"{3}|$)|'{3}[\\s\\S]*?(?:'{3}|$)|\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*'))",
    "(#.*$)",
    "(\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)",
    "(@\\w+)",
    "(\\w+)",
    "(\\s+)",
    "(.)",
  ].join("|"),
  "gm",
);

export function tokenizePythonLine(line: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  PY_TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = PY_TOKEN_RE.exec(line)) !== null) {
    const text = m[0];
    let color = PY_COLORS.default;
    if (m[1]) color = PY_COLORS.string;
    else if (m[2]) color = PY_COLORS.comment;
    else if (m[3]) color = PY_COLORS.number;
    else if (m[4]) color = PY_COLORS.decorator;
    else if (m[5]) {
      if (PY_KEYWORDS.has(text)) color = PY_COLORS.keyword;
      else if (PY_BUILTINS.has(text)) color = PY_COLORS.builtin;
    }
    tokens.push({ text, color });
  }
  return tokens;
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function isPythonLang(lang?: string): boolean {
  if (!lang) return false;
  return /^(?:python|py|python3|py3)$/i.test(lang);
}
