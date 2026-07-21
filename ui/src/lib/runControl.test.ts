import { describe, it, expect } from "vitest";
import { controlUiState } from "./runControl";

describe("controlUiState", () => {
  it("running: offers Pause + Stop, no banner", () => {
    const s = controlUiState("running", "running", "running");
    expect(s.live).toBe(true);
    expect(s.banner).toBeNull();
    expect(s.buttons).toEqual([
      { action: "pause", disabled: false },
      { action: "stop", disabled: false },
    ]);
  });

  it("pausing (desired paused, acked running): 'pausing…', Pause disabled, Stop enabled", () => {
    const s = controlUiState("paused", "running", "running");
    expect(s.banner).toBe("pausing…");
    expect(s.buttons).toEqual([
      { action: "pause", disabled: true },
      { action: "stop", disabled: false },
    ]);
  });

  it("paused (both paused): 'paused', offers Resume + Stop", () => {
    const s = controlUiState("paused", "paused", "running");
    expect(s.banner).toBe("paused");
    expect(s.buttons).toEqual([
      { action: "resume", disabled: false },
      { action: "stop", disabled: false },
    ]);
  });

  it("stopping (desired stopped): 'stopping…', Stop disabled", () => {
    const s = controlUiState("stopped", "running", "running");
    expect(s.banner).toBe("stopping…");
    expect(s.buttons).toEqual([{ action: "stop", disabled: true }]);
  });

  it.each(["success", "error", "stopped"] as const)("terminal run (%s): bar hidden", (status) => {
    const s = controlUiState("running", "running", status);
    expect(s.live).toBe(false);
    expect(s.buttons).toEqual([]);
  });

  it("waiting for input: banner + Stop only, Pause hidden, awaitingInput flag set", () => {
    const s = controlUiState("running", "running", "running", true);
    expect(s.banner).toBe("waiting for your input");
    expect(s.awaitingInput).toBe(true);
    expect(s.buttons).toEqual([{ action: "stop", disabled: false }]);
  });

  it("stop takes precedence over waiting for input", () => {
    const s = controlUiState("stopped", "running", "running", true);
    expect(s.banner).toBe("stopping…");
    expect(s.awaitingInput).toBe(false);
  });

  it("waiting flag is ignored once the run is terminal", () => {
    const s = controlUiState("running", "running", "success", true);
    expect(s.live).toBe(false);
    expect(s.awaitingInput).toBe(false);
  });

  it("non-waiting running keeps awaitingInput false", () => {
    expect(controlUiState("running", "running", "running").awaitingInput).toBe(false);
    expect(controlUiState("paused", "paused", "running").awaitingInput).toBe(false);
  });
});
