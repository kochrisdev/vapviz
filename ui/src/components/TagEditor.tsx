import { useState } from "react";
import { Plus, Tag, X } from "lucide-react";
import { useRunStore } from "../store/runStore";

interface Props {
  runId: string;
  tags: string[];
}

/** Inline editor for a run's tags — chips with remove, plus an add input. */
export function TagEditor({ runId, tags }: Props) {
  const setRunTags = useRunStore((s) => s.setRunTags);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  const save = async (next: string[]) => {
    // optimistic update, then persist
    setRunTags(runId, next);
    try {
      const r = await fetch(`/runs/${runId}/tags`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags: next }),
      });
      if (r.ok) setRunTags(runId, await r.json());
    } catch {
      /* poll will reconcile */
    }
  };

  const addTag = () => {
    const t = draft.trim();
    if (t && !tags.includes(t)) save([...tags, t]);
    setDraft("");
    setAdding(false);
  };

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <Tag size={11} className="text-content-faint shrink-0" />
      {tags.map((t) => (
        <span
          key={t}
          className="group/tag flex items-center gap-1 text-[10px] bg-surface-hover text-content-muted border border-border px-1.5 py-0.5 rounded-full"
        >
          {t}
          <button
            onClick={() => save(tags.filter((x) => x !== t))}
            title="Remove tag"
            className="text-content-faint hover:text-status-error"
          >
            <X size={9} />
          </button>
        </span>
      ))}
      {adding ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={addTag}
          onKeyDown={(e) => {
            if (e.key === "Enter") addTag();
            if (e.key === "Escape") { setDraft(""); setAdding(false); }
          }}
          placeholder="tag…"
          className="bg-surface-inset text-[10px] text-content placeholder-content-faint outline-none border border-border rounded-full px-2 py-0.5 w-20"
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          title="Add tag"
          className="flex items-center gap-0.5 text-[10px] text-content-faint hover:text-accent border border-dashed border-border hover:border-accent/40 px-1.5 py-0.5 rounded-full"
        >
          <Plus size={9} /> tag
        </button>
      )}
    </div>
  );
}
