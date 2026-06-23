/**
 * Display-only secret redaction (UI-ROADMAP §4-B). Masks values stored under
 * secret-ish keys and obvious key shapes inside strings. Never mutates stored
 * data — returns a redacted copy for rendering.
 */

const SECRET_KEY_RE = /(api[_-]?key|secret|token|authorization|password|access[_-]?key|bearer)/i;
const MASK = "••••••";

/** Mask key shapes embedded in free text (sk-…, Bearer …). */
export function maskString(s: string): string {
  return s
    .replace(/\b(sk|pk|rk)-[A-Za-z0-9_-]{6,}/g, "$1-" + MASK)
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer " + MASK);
}

/** Deep-redact a JSON-ish value for display. */
export function redact(value: unknown): unknown {
  if (typeof value === "string") return maskString(value);
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SECRET_KEY_RE.test(k) && typeof v === "string" ? MASK : redact(v);
    }
    return out;
  }
  return value;
}
