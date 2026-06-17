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
      <Tag size={11} className="text-slate-500 shrink-0" />
      {tags.map((t) => (
        <span
          key={t}
          className="group/tag flex items-center gap-1 text-[10px] bg-slate-700/60 text-slate-300 border border-slate-600/60 px-1.5 py-0.5 rounded-full"
        >
          {t}
          <button
            onClick={() => save(tags.filter((x) => x !== t))}
            title="Remove tag"
            className="text-slate-500 hover:text-red-400"
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
          className="bg-slate-800 text-[10px] text-slate-200 placeholder-slate-600 outline-none border border-slate-600 rounded-full px-2 py-0.5 w-20"
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          title="Add tag"
          className="flex items-center gap-0.5 text-[10px] text-slate-500 hover:text-indigo-300 border border-dashed border-slate-600/60 hover:border-indigo-500/40 px-1.5 py-0.5 rounded-full"
        >
          <Plus size={9} /> tag
        </button>
      )}
    </div>
  );
}
