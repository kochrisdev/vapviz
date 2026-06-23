import { Sparkles, Wrench } from "lucide-react";
import { useRunStore } from "../store/runStore";
import type { AppMode } from "../store/runStore";

/** Global Simple ⇄ Technical audience switch (UI-ROADMAP redesign). */
export function ModeToggle() {
  const mode = useRunStore((s) => s.mode);
  const setMode = useRunStore((s) => s.setMode);

  const btn = (value: AppMode, label: string, Icon: typeof Sparkles, title: string) => (
    <button
      onClick={() => setMode(value)}
      title={title}
      className={`flex-1 flex items-center justify-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-md transition-colors ${
        mode === value
          ? "bg-accent text-content-on-accent shadow-sm"
          : "text-content-muted hover:text-content hover:bg-surface-hover"
      }`}
    >
      <Icon size={15} /> {label}
    </button>
  );

  return (
    <div className="flex items-center gap-1 bg-surface-inset border-b border-border p-2">
      {btn("simple", "Simple", Sparkles, "Plain-language view for everyone")}
      {btn("technical", "Technical", Wrench, "Graph, logs, and raw data")}
    </div>
  );
}
