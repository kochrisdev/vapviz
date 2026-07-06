import { describe, expect, it } from "vitest";
import type { NodeStatus, RunSummary } from "../types/events";
import {
  ROOMS_PER_FLOOR,
  appKey,
  buildBuilding,
  groupApps,
  pruneDismissed,
  type Building,
} from "./building";

/* ── fixtures ────────────────────────────────────────────────────────────── */

let seq = 0;
function run(opts: {
  id?: string;
  label?: string;
  app_id?: string | null;
  status?: NodeStatus;
  started_at?: number;
}): RunSummary {
  seq += 1;
  return {
    run_id: opts.id ?? `run-${seq}`,
    label: opts.label ?? "My app",
    app_id: opts.app_id,
    status: opts.status ?? "success",
    started_at: opts.started_at ?? seq,
    ended_at: null,
    node_count: 1,
    event_count: 2,
    total_cost_usd: null,
    tags: [],
  };
}

const NONE = new Set<string>();

/** {appKey: {floor, room}} for every occupied room — position assertions. */
function positions(b: Building): Record<string, { floor: number; room: number }> {
  const out: Record<string, { floor: number; room: number }> = {};
  b.floors.forEach((f) =>
    f.rooms.forEach((r, i) => {
      if (r) out[r.appKey] = { floor: f.index, room: i };
    })
  );
  return out;
}

/* ── grouping ────────────────────────────────────────────────────────────── */

describe("appKey / groupApps", () => {
  it("groups by app_id, falls back to exact label, mixes both", () => {
    const runs = [
      run({ app_id: "bot", label: "Support bot v1" }),
      run({ app_id: "bot", label: "Support bot v2" }),
      run({ label: "Scraper" }), // no app_id → label
      run({ label: "Scraper" }),
      run({ label: "One-off" }),
    ];
    const groups = groupApps(runs);
    const keys = groups.map((g) => g.appKey).sort();
    expect(keys).toEqual(["One-off", "Scraper", "bot"]);
    expect(groups.find((g) => g.appKey === "bot")?.runs).toHaveLength(2);
    expect(groups.find((g) => g.appKey === "Scraper")?.runs).toHaveLength(2);
  });

  it("appKey treats null, missing and EMPTY app_id alike (label fallback)", () => {
    expect(appKey(run({ app_id: null, label: "L" }))).toBe("L");
    expect(appKey(run({ label: "L" }))).toBe("L");
    expect(appKey(run({ app_id: "", label: "L" }))).toBe("L"); // "" must not merge unrelated apps
    expect(appKey(run({ app_id: "a", label: "L" }))).toBe("a");
  });

  it("current run: any running wins over a newer finished run", () => {
    const older = run({ app_id: "bot", status: "running", started_at: 10 });
    const newer = run({ app_id: "bot", status: "success", started_at: 20 });
    const g = groupApps([older, newer])[0];
    expect(g.current.run_id).toBe(older.run_id);
  });

  it("current run: two concurrent running runs → most-recently-started", () => {
    const a = run({ app_id: "bot", status: "running", started_at: 10 });
    const b = run({ app_id: "bot", status: "running", started_at: 20 });
    const g = groupApps([a, b])[0];
    expect(g.current.run_id).toBe(b.run_id);
  });

  it("current run: no running → newest by started_at", () => {
    const a = run({ app_id: "bot", status: "success", started_at: 10 });
    const b = run({ app_id: "bot", status: "error", started_at: 20 });
    expect(groupApps([a, b])[0].current.run_id).toBe(b.run_id);
  });
});

/* ── seating + stickiness ────────────────────────────────────────────────── */

describe("buildBuilding — seating", () => {
  it("seats new apps on the top floor; rooms are fixed at 6", () => {
    const runs = [run({ app_id: "a" }), run({ app_id: "b" }), run({ app_id: "c" })];
    const b = buildBuilding(runs, null, NONE);
    expect(b.floors).toHaveLength(1);
    expect(b.floors[0].rooms).toHaveLength(ROOMS_PER_FLOOR);
    expect(Object.values(positions(b)).every((p) => p.floor === 0)).toBe(true);
    expect(b.incidentHall).toEqual([]);
  });

  it("re-run stickiness: an app keeps its exact room across ticks", () => {
    const first = buildBuilding(
      [run({ app_id: "a", started_at: 1 }), run({ app_id: "b", started_at: 2 })],
      null,
      NONE
    );
    const seat = positions(first)["a"];

    // next tick: app "a" re-runs (new running run) — same room, new current run
    const rerun = run({ app_id: "a", status: "running", started_at: 50 });
    const second = buildBuilding(
      [run({ app_id: "a", started_at: 1 }), rerun, run({ app_id: "b", started_at: 2 })],
      first,
      NONE
    );
    expect(positions(second)["a"]).toEqual(seat);
    const room = second.floors[seat.floor].rooms[seat.room]!;
    expect(room.currentRunId).toBe(rerun.run_id);
    expect(room.status).toBe("running");
    expect(room.runCount).toBe(2);
  });

  it("a vanished app frees its room; the slot stays put for the others", () => {
    const first = buildBuilding(
      [run({ app_id: "a" }), run({ app_id: "b" }), run({ app_id: "c" })],
      null,
      NONE
    );
    const seatC = positions(first)["c"];
    const second = buildBuilding(
      [run({ app_id: "a" }), run({ app_id: "c" })],
      first,
      NONE
    );
    expect(positions(second)["c"]).toEqual(seatC);
    expect(positions(second)["b"]).toBeUndefined();
  });
});

/* ── incident hall + dismiss ─────────────────────────────────────────────── */

describe("buildBuilding — incident hall", () => {
  it("an errored current run pulls the app into the hall and frees its room", () => {
    const ok = run({ app_id: "a", status: "success" });
    const first = buildBuilding([ok], null, NONE);
    const failed = run({ app_id: "a", status: "error", started_at: 99 });
    const second = buildBuilding([ok, failed], first, NONE);
    expect(positions(second)["a"]).toBeUndefined();
    expect(second.incidentHall.map((r) => r.appKey)).toEqual(["a"]);
    expect(second.incidentHall[0].currentRunId).toBe(failed.run_id);
  });

  it("dismiss removes the app from the building entirely", () => {
    const failed = run({ app_id: "a", status: "error" });
    const b = buildBuilding([failed], null, new Set([failed.run_id]));
    expect(b.incidentHall).toEqual([]);
    expect(positions(b)["a"]).toBeUndefined();
  });

  it("the app's next run re-enters the building; a NEW failure re-flags", () => {
    const failed = run({ app_id: "a", status: "error", started_at: 1 });
    const dismissed = new Set([failed.run_id]);

    // new healthy run → back in a room despite the old dismissal
    const healthy = run({ app_id: "a", status: "running", started_at: 2 });
    const b1 = buildBuilding([failed, healthy], null, dismissed);
    expect(positions(b1)["a"]).toBeDefined();
    expect(b1.incidentHall).toEqual([]);

    // that run fails too (different run_id) → hall again
    const failedAgain = run({ app_id: "a", status: "error", started_at: 2 });
    const b2 = buildBuilding([failed, failedAgain], b1, dismissed);
    expect(b2.incidentHall.map((r) => r.appKey)).toEqual(["a"]);
  });

  it("an older running run keeps an app in its room even if the newest run errored", () => {
    const running = run({ app_id: "a", status: "running", started_at: 1 });
    const failed = run({ app_id: "a", status: "error", started_at: 2 });
    const b = buildBuilding([running, failed], null, NONE);
    expect(positions(b)["a"]).toBeDefined();
    expect(b.incidentHall).toEqual([]);
  });
});

/* ── descent ─────────────────────────────────────────────────────────────── */

function fullTopFloor(statuses: NodeStatus[]): { runs: RunSummary[]; prev: Building } {
  const runs = statuses.map((status, i) =>
    run({ app_id: `app-${i}`, status, started_at: (i + 1) * 10 })
  );
  return { runs, prev: buildBuilding(runs, null, NONE) };
}

describe("buildBuilding — descent under pressure", () => {
  it("full top floor + new app → oldest FINISHED app descends", () => {
    const { runs, prev } = fullTopFloor([
      "running", // app-0, oldest, but running
      "success", // app-1 ← oldest finished: descends
      "success",
      "running",
      "success",
      "running",
    ]);
    const arrival = run({ app_id: "new", status: "running", started_at: 100 });
    const b = buildBuilding([...runs, arrival], prev, NONE);
    const pos = positions(b);
    expect(b.floors).toHaveLength(2);
    expect(pos["app-1"].floor).toBe(1);
    expect(pos["new"]).toEqual({ floor: 0, room: 1 }); // takes the vacated slot
    expect(pos["app-0"].floor).toBe(0); // running stays despite being oldest
  });

  it("all top-floor apps running → earliest-started running app descends, still live", () => {
    const { runs, prev } = fullTopFloor([
      "running",
      "running",
      "running",
      "running",
      "running",
      "running",
    ]);
    const arrival = run({ app_id: "new", status: "running", started_at: 100 });
    const b = buildBuilding([...runs, arrival], prev, NONE);
    const pos = positions(b);
    expect(pos["app-0"]).toEqual({ floor: 1, room: 0 });
    expect(b.floors[1].rooms[0]!.status).toBe("running"); // live below
    expect(pos["new"]).toEqual({ floor: 0, room: 0 });
  });

  it("cascades: full floor 1 pushes its earliest down to a new floor 2", () => {
    // 12 finished apps fill floors 0+1 via successive pressure
    let building: Building | null = null;
    const roster: RunSummary[] = [];
    for (let i = 0; i < 12; i++) {
      roster.push(run({ app_id: `app-${i}`, status: "success", started_at: (i + 1) * 10 }));
      building = buildBuilding(roster, building, NONE);
    }
    expect(building!.floors).toHaveLength(2);

    // one more: floor 0's earliest descends to floor 1 (full) → ITS earliest → floor 2
    roster.push(run({ app_id: "new", status: "running", started_at: 999 }));
    const b = buildBuilding(roster, building, NONE);
    expect(b.floors).toHaveLength(3);
    expect(b.floors[2].rooms.filter(Boolean)).toHaveLength(1);
    expect(positions(b)["new"].floor).toBe(0);
    // never sideways
    for (const f of b.floors) expect(f.rooms).toHaveLength(ROOMS_PER_FLOOR);
  });

  it("the building shrinks when trailing floors empty out", () => {
    const { runs, prev } = fullTopFloor([
      "success",
      "success",
      "success",
      "success",
      "success",
      "success",
    ]);
    const arrival = run({ app_id: "new", status: "running", started_at: 100 });
    const grown = buildBuilding([...runs, arrival], prev, NONE);
    expect(grown.floors).toHaveLength(2);

    // the descended app's run disappears from the roster → floor 1 empties → trimmed
    const descended = Object.entries(positions(grown)).find(([, p]) => p.floor === 1)![0];
    const shrunk = buildBuilding(
      [...runs.filter((r) => appKey(r) !== descended), arrival],
      grown,
      NONE
    );
    expect(shrunk.floors).toHaveLength(1);
  });
});

/* ── determinism + pruning ───────────────────────────────────────────────── */

describe("determinism", () => {
  it("same inputs → identical output (including across object identity)", () => {
    const runs = [
      run({ app_id: "a", status: "running", started_at: 5 }),
      run({ app_id: "b", status: "error", started_at: 6 }),
      run({ label: "c", started_at: 7 }),
    ];
    const prev = buildBuilding(runs.slice(0, 2), null, NONE);
    const x = buildBuilding(runs, prev, NONE);
    const y = buildBuilding(runs.map((r) => ({ ...r })), JSON.parse(JSON.stringify(prev)), NONE);
    expect(x).toEqual(y);
  });
});

describe("pruneDismissed", () => {
  it("drops ids whose run left the roster, keeps live ones", () => {
    const alive = run({ app_id: "a", status: "error" });
    const pruned = pruneDismissed([alive.run_id, "gone-run"], [alive]);
    expect(pruned).toEqual(new Set([alive.run_id]));
  });
});
