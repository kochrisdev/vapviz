import { CheckCircle2, Circle, Loader2, OctagonX, XCircle, type LucideIcon } from "lucide-react";
import type { NodeStatus } from "../types/events";

// Status is always colour + icon so it stays colourblind-safe.
const STATUS: Record<NodeStatus, { token: string; icon: LucideIcon; label: string; spin?: boolean }> = {
  pending: { token: "--status-pending", icon: Circle, label: "pending" },
  running: { token: "--status-running", icon: Loader2, label: "running", spin: true },
  success: { token: "--status-success", icon: CheckCircle2, label: "success" },
  error: { token: "--status-error", icon: XCircle, label: "error" },
  stopped: { token: "--status-stopped", icon: OctagonX, label: "stopped" },
};

interface Props {
  status: NodeStatus;
  /** Show the text label alongside the icon (default true). */
  showLabel?: boolean;
  className?: string;
}

export function StatusBadge({ status, showLabel = true, className = "" }: Props) {
  const s = STATUS[status] ?? STATUS.pending;
  const Icon = s.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[9px] px-display px-2 py-0.5 border-2 ${className}`}
      style={{
        color: `rgb(var(${s.token}))`,
        background: `rgb(var(${s.token}) / 0.15)`,
        borderColor: `rgb(var(${s.token}) / 0.45)`,
      }}
    >
      <Icon size={10} className={s.spin ? "animate-spin" : undefined} />
      {showLabel && s.label}
    </span>
  );
}
