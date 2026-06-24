import type { GraphNode } from "../types/events";
import { formatLabel } from "./format";
import { maskString } from "./redact";

/**
 * Plain-language "what happened" for a single node — the readable alternative
 * to raw JSON (UI-ROADMAP redesign). Deterministic, template-only. All
 * user-content strings are passed through `maskString` so secrets don't leak
 * into the explanation.
 */

function clip(s: string, n: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t;
}

function safe(s: string, n: number): string {
  return maskString(clip(s, n));
}

function stripModel(label: string): string {
  let l = label;
  if (l.startsWith("llm/")) l = l.slice(4);
  if (l.includes("/")) l = l.slice(l.lastIndexOf("/") + 1);
  return l;
}

function lastUserMessage(input: Record<string, unknown> | undefined): string | null {
  if (!input) return null;
  const msgs = input.messages as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(msgs)) {
    const u = [...msgs].reverse().find((m) => m.role === "user" || m.type === "human");
    if (u && typeof u.content === "string" && u.content.trim()) return u.content.trim();
  }
  if (typeof input.prompt === "string" && input.prompt.trim()) return input.prompt.trim();
  return null;
}

function replyText(output: Record<string, unknown> | undefined): string | null {
  if (!output) return null;
  for (const k of ["text", "output", "response", "result"]) {
    const v = output[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

/** Render tool arguments as `key=value, …` (parsing a JSON-string if needed). */
export function readableArgs(input: Record<string, unknown> | undefined): string | null {
  if (!input) return null;
  let args: unknown = "args" in input ? input.args : input;
  if (typeof args === "string") {
    const str = args;
    try {
      args = JSON.parse(str);
    } catch {
      return safe(str, 80);
    }
  }
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const parts = Object.entries(args as Record<string, unknown>)
      // drop noisy non-arg keys when we fell back to the whole input object
      .filter(([k]) => !["model", "messages", "tools", "max_tokens"].includes(k))
      .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
    return parts.length ? safe(parts.join(", "), 100) : null;
  }
  return null;
}

export function readableResult(output: Record<string, unknown> | undefined): string | null {
  if (!output) return null;
  const r = "result" in output ? output.result : "output" in output ? output.output : output;
  if (r == null) return null;
  const s = typeof r === "string" ? r : JSON.stringify(r);
  return safe(s, 160);
}

export function explainNode(node: GraphNode): string {
  const input = node.data?.input as Record<string, unknown> | undefined;
  const output = node.data?.output as Record<string, unknown> | undefined;

  if (node.status === "error") {
    const err = (node.data?.error as unknown) ?? output?.error;
    return err ? `This step failed: ${safe(String(err), 160)}` : "This step failed.";
  }

  switch (node.kind) {
    case "llm": {
      const model = typeof input?.model === "string" ? stripModel(input.model) : "the model";
      const ask = lastUserMessage(input);
      const reply = replyText(output);
      let s = ask ? `Asked ${model}: “${safe(ask, 160)}”` : `Sent a request to ${model}`;
      if (reply) s += `. It replied: “${safe(reply, 220)}”`;
      return s.endsWith("”") ? s + "." : s + ".";
    }
    case "tool": {
      const name = formatLabel(node);
      const a = readableArgs(input);
      const r = readableResult(output);
      let s = a ? `Ran the tool ${name} with ${a}` : `Ran the tool ${name}`;
      if (r) s += ` → returned “${r}”`;
      return s + ".";
    }
    case "agent":
      return "The top-level agent for this run — expand the steps to see what it did.";
    case "step":
    default: {
      const name = formatLabel(node);
      const ask = lastUserMessage(input);
      const reply = replyText(output);
      if (!ask && !reply) return `Ran the “${name}” step.`;
      let s = `“${name}”`;
      if (ask) s += ` — input: “${safe(ask, 120)}”`;
      if (reply) s += `${ask ? ";" : " —"} result: “${safe(reply, 160)}”`;
      return s + ".";
    }
  }
}
