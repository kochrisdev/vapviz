import { useEffect, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";
import type { NodeStatus, VapEvent } from "../types/events";
import type { ControlLatch } from "../hooks/useControlLatch";
import { toTurns, type Turn } from "../lib/conversation";

/**
 * The two-way conversation surface (Layer 2b), docked beside the office scene in
 * the Theater tab. Renders the agent ↔ user back-and-forth from the run's inert
 * `control` events (actions ask / say / input, derived by the pure `toTurns`) —
 * so it works live over SSE *and* as a read-only transcript once the run has
 * ended — plus a reply box that lights up when the agent is waiting
 * (ask()/take_input()).
 *
 * UI-only side channel (not dual-logic): it re-presents already-streamed events
 * and reads/writes the control latch via the shared `useControlLatch` hook.
 * See docs/notes/DESIGN-agent-control.md §29-38.
 */

export function ConversationPanel({
  events,
  runStatus,
  latch,
  sendMessage,
}: {
  events: VapEvent[];
  runStatus: NodeStatus;
  latch: ControlLatch | null;
  sendMessage: (text: string) => Promise<boolean>;
}) {
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const turns = useMemo(() => toTurns(events), [events]);

  const live = runStatus === "running";
  const waiting = live && (latch?.waiting_for_input ?? false);
  const question = waiting ? latch?.question ?? null : null;
  const pending = live && (latch?.pending_input ?? false);

  // Keep the newest turn in view (and re-anchor when the agent starts waiting).
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, waiting]);

  const submit = async () => {
    const text = message.trim();
    if (!text || sending) return;
    setSending(true);
    const ok = await sendMessage(text);
    if (ok) setMessage("");
    setSending(false);
  };

  return (
    <div className="flex flex-col h-full min-h-0 w-72 shrink-0 border-l-2 border-border bg-surface-inset">
      <div className="flex items-center gap-2 px-3 py-2 border-b-2 border-border shrink-0">
        <span className="px-display text-[10px] text-content-muted">💬 Conversation</span>
        {waiting && (
          <span className="px-display text-[9px] text-status-running animate-pulse ml-auto">waiting…</span>
        )}
      </div>

      {/* Transcript */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-2">
        {turns.length === 0 ? (
          <p className="text-[11px] text-content-faint leading-relaxed mt-1">
            No messages yet. The agent can ask you a question with{" "}
            <code className="font-mono text-content-muted">vapviz.ask()</code> or speak up with{" "}
            <code className="font-mono text-content-muted">vapviz.say()</code>; you can steer it any
            time with the box below.
          </p>
        ) : (
          turns.map((t) => <Bubble key={t.id} turn={t} />)
        )}
      </div>

      {/* Reply box — the open question (if any) sits right above it */}
      {live ? (
        <form
          className="shrink-0 border-t-2 border-border px-3 py-2.5 flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {question && (
            <div className="px-display text-[10px] text-status-running leading-snug">
              Agent asks: <span className="text-content">{question}</span>
            </div>
          )}
          {pending && !waiting && (
            <span
              className="px-display text-[9px] text-content-faint"
              title="Delivered to the agent's mailbox; it will pick this up at its next checkpoint."
            >
              delivered — awaiting pickup
            </span>
          )}
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={waiting ? "type your answer…" : "message the agent…"}
              autoFocus={waiting}
              aria-label="Message the agent"
              className={`flex-1 min-w-0 font-mono text-[13px] leading-none px-2 py-1.5 bg-surface border-2 outline-none transition-colors placeholder:text-content-faint ${
                waiting ? "border-status-running" : "border-border focus:border-content-muted"
              }`}
            />
            <button
              type="submit"
              disabled={sending || !message.trim()}
              title="Send this message to the agent"
              className="flex items-center gap-1 px-display text-[10px] px-2.5 py-2 border-2 border-border text-content hover:bg-surface-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Send size={12} />
            </button>
          </div>
        </form>
      ) : (
        <div className="shrink-0 border-t-2 border-border px-3 py-2 px-display text-[9px] text-content-faint">
          run ended — transcript is read-only
        </div>
      )}
    </div>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  const isUser = turn.who === "user";
  const isAsk = turn.kind === "ask";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <span className="px-display text-[8px] text-content-faint mb-0.5 px-0.5">
        {isUser ? "you" : isAsk ? "agent asks" : "agent"}
      </span>
      <div
        className={`max-w-[90%] text-[12px] leading-snug px-2.5 py-1.5 border-2 whitespace-pre-wrap break-words ${
          isUser
            ? "bg-surface border-border text-content"
            : isAsk
              ? "bg-status-running/10 border-status-running/50 text-content"
              : "bg-surface border-border/60 text-content-muted"
        }`}
      >
        {turn.text}
      </div>
    </div>
  );
}
