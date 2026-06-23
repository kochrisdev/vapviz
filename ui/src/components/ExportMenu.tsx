import { useState, useCallback } from "react";
import { Download, ChevronDown, FileJson, Image } from "lucide-react";
import { cssColor } from "../lib/cssColor";

interface Props {
  runId: string;
  label: string;
  graphContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function ExportMenu({ runId, label, graphContainerRef }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleJson = useCallback(async () => {
    setOpen(false);
    const resp = await fetch(`/runs/${runId}/export`);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vapviz-${runId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [runId]);

  const handlePng = useCallback(async () => {
    setOpen(false);
    const el = graphContainerRef.current;
    if (!el) return;
    setBusy(true);
    try {
      // Dynamic import so html2canvas is only loaded on demand
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(el, {
        backgroundColor: cssColor("--bg"),
        logging: false,
        useCORS: true,
      });
      canvas.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `vapviz-${label}-${runId}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, "image/png");
    } finally {
      setBusy(false);
    }
  }, [runId, label, graphContainerRef]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        className="flex items-center gap-1 text-xs text-content-faint hover:text-content bg-surface-inset hover:bg-surface-hover disabled:opacity-50 px-2 py-1 rounded border border-border transition-colors"
      >
        <Download size={12} />
        {busy ? "Exporting…" : "Export"}
        {!busy && <ChevronDown size={11} />}
      </button>

      {open && (
        <>
          {/* Click-away overlay */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 bg-surface border border-border rounded shadow-xl py-1 min-w-[140px]">
            <button
              onClick={handleJson}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-content-muted hover:bg-surface-hover hover:text-content transition-colors"
            >
              <FileJson size={12} />
              Download JSON
            </button>
            <button
              onClick={handlePng}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-content-muted hover:bg-surface-hover hover:text-content transition-colors"
            >
              <Image size={12} />
              Download PNG
            </button>
          </div>
        </>
      )}
    </div>
  );
}
