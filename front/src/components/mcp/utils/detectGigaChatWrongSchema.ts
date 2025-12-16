// Detects incorrect usage of anyOf/allOf in GigaChat schemas.
// Rules:
// - anyOf: allowed only when it represents nullable type (exactly one non-null type; any number of 'null' entries).
//          If there are 2+ different non-null types OR a single variant lists multiple non-null types, it's incorrect.
// - allOf: incorrect when it combines more than 2 distinct non-null types across its variants.
//
// The function traverses the entire schema recursively.

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractTypes(node: unknown): string[] {
  if (!isObject(node)) return [];
  const t = (node as JsonObject)["type"];
  if (typeof t === "string") return [t];
  if (Array.isArray(t))
    return t.filter((v): v is string => typeof v === "string");
  return [];
}

export function detectGigaChatWrongSchema(schema: unknown): boolean {
  const visited = new WeakSet<object>();

  function walk(node: unknown): boolean {
    if (Array.isArray(node)) {
      for (const item of node) {
        if (walk(item)) return true;
      }
      return false;
    }

    if (!isObject(node)) return false;
    if (visited.has(node)) return false;
    visited.add(node);

    // Check anyOf rule
    const anyOf = node["anyOf"];
    if (Array.isArray(anyOf)) {
      const nonNullTypes = new Set<string>();
      for (const variant of anyOf) {
        const types = extractTypes(variant).filter((t) => t !== "null");
        // A single variant that itself declares multiple non-null types is incorrect
        if (types.length > 1) return true;
        for (const t of types) {
          nonNullTypes.add(t);
          // Early exit if we already see more than one non-null type across variants
          if (nonNullTypes.size > 1) return true;
        }
      }
      // If here, either 0 or 1 non-null types were found → acceptable (nullable or constrained single type)
    }

    // Check allOf rule
    const allOf = node["allOf"];
    if (Array.isArray(allOf)) {
      const allOfTypes = new Set<string>();
      for (const variant of allOf) {
        const types = extractTypes(variant).filter((t) => t !== "null");
        for (const t of types) {
          allOfTypes.add(t);
          if (allOfTypes.size > 2) return true; // more than 2 non-null distinct types → incorrect
        }
      }
    }

    // Recurse into all object values
    for (const value of Object.values(node)) {
      if (walk(value)) return true;
    }
    return false;
  }

  return walk(schema);
}
