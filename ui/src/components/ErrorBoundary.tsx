import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** What the fallback says broke, e.g. "the detail panel" (default: "this view"). */
  label?: string;
}

interface State {
  error: Error | null;
}

/**
 * Catches render errors so one bad node/run can never blank the whole app —
 * event data is arbitrary user input, so anything that renders it can throw.
 * Remount (e.g. with a `key`) or "Try again" resets it.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("vapviz view crashed:", error);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex-1 h-full flex flex-col items-center justify-center gap-3 p-6 text-center bg-bg text-content">
        <div className="h-11 w-11 rounded-xl bg-status-error/10 border border-status-error/25 flex items-center justify-center">
          <AlertTriangle size={20} className="text-status-error" />
        </div>
        <div>
          <p className="font-medium mb-1">Something went wrong showing {this.props.label ?? "this view"}</p>
          <p className="text-content-faint text-sm max-w-sm leading-relaxed">
            The rest of the app is fine — this data couldn't be displayed.
          </p>
          <p className="text-content-faint text-xs mt-2 font-mono break-all max-w-sm mx-auto">
            {this.state.error.message}
          </p>
        </div>
        <button
          onClick={() => this.setState({ error: null })}
          className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-md bg-surface-inset border border-border text-content-muted hover:text-content hover:bg-surface-hover transition-colors"
        >
          <RotateCcw size={13} /> Try again
        </button>
      </div>
    );
  }
}
