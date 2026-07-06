import type { NodeStatus, RunSummary } from "../types/events";

/**
 * The Office Building reducer (UI-ROADMAP §4-I, spec in Appendix A.6).
 *
 * Re-keys the Floor from run instances to *apps*: app = room, agent = desk.
 * Pure — no canvas, no clock, no network. Seeded by the previous tick's
 * result so rooms stay sticky; NOT part of the dual-logic parity rule
 * (it re-presents already-derived data, like theater.ts/officeScene.ts).
 *
 * Placement, in order:
 *   1. stay put — every surviving app keeps its exact {floor, room}
 *   2. errors → top-floor incident hall (dismissed → out until the next run)
 *   3. new apps seat on the top floor
 *   4. full top floor → the earliest app descends (finished preferred;
 *      all-running → earliest-started running descends, stays live below);
 *      cascade downward, floors appended at the bottom, never sideways
 */

export const ROOMS_PER_FLOOR = 6;

export interface AppRoom {
  appKey: string; // grouping key: app_id ?? label
  label: string;
  currentRunId: string; // the run that drives the room (running wins; else newest)
  status: NodeStatus; // of the current run
  runCount: number; // for the "×N" affordance
  startedAt: number; // current run's started_at — drives "earliest" in descent
}

export interface Floor {
  index: number;
  rooms: (AppRoom | null)[]; // fixed length ROOMS_PER_FLOOR
}

export interface Building {
  floors: Floor[];
  incidentHall: AppRoom[]; // lives on the top floor, extra slot(s)
}

export interface AppGroup {
  appKey: string;
  label: string;
  current: RunSummary;
  runs: RunSummary[]; // newest first
}

/** Grouping key shared by the building and the sidebar — they must never disagree.
 *  `||` (not `??`): an empty-string app_id must also fall back to the label, or every
 *  run that slipped through with app_id="" would merge into one "" app. */
export function appKey(run: RunSummary): string {
  return run.app_id || run.label;
}

/** Deterministic tiebreak so equal timestamps can't reorder between ticks. */
function byNewest(a: RunSummary, b: RunSummary): number {
  return b.started_at - a.started_at || a.run_id.localeCompare(b.run_id);
}

/** The run that drives an app: any running run wins (most-recently-started if several); else newest. */
function pickCurrent(runs: RunSummary[]): RunSummary {
  const running = runs.filter((r) => r.status === "running");
  const pool = running.length ? running : runs;
  return [...pool].sort(byNewest)[0];
}

/** Group a /runs roster into apps, newest activity first. */
export function groupApps(runs: RunSummary[]): AppGroup[] {
  const byKey = new Map<string, RunSummary[]>();
  for (const r of runs) {
    const k = appKey(r);
    const list = byKey.get(k);
    if (list) list.push(r);
    else byKey.set(k, [r]);
  }
  return [...byKey.entries()]
    .map(([k, rs]) => {
      const current = pickCurrent(rs);
      return { appKey: k, label: current.label, current, runs: [...rs].sort(byNewest) };
    })
    .sort(
      (a, b) =>
        b.current.started_at - a.current.started_at || a.appKey.localeCompare(b.appKey)
    );
}

function toRoom(g: AppGroup): AppRoom {
  return {
    appKey: g.appKey,
    label: g.label,
    currentRunId: g.current.run_id,
    status: g.current.status,
    runCount: g.runs.length,
    startedAt: g.current.started_at,
  };
}

function emptyRow(): (AppRoom | null)[] {
  return Array(ROOMS_PER_FLOOR).fill(null);
}

/** Descent victim: oldest finished preferred; all running → earliest-started running. */
function pickEarliest(rooms: (AppRoom | null)[]): number {
  const occupied = rooms
    .map((room, slot) => ({ room, slot }))
    .filter((x): x is { room: AppRoom; slot: number } => x.room !== null);
  const finished = occupied.filter((x) => x.room.status !== "running");
  const pool = finished.length ? finished : occupied;
  pool.sort(
    (a, b) =>
      a.room.startedAt - b.room.startedAt || a.room.appKey.localeCompare(b.room.appKey)
  );
  return pool.length ? pool[0].slot : -1;
}

/** Place *room* on *floorIdx*: free slot if any, else evict the earliest one floor down. */
function placeOn(floors: (AppRoom | null)[][], room: AppRoom, floorIdx: number): void {
  while (floors.length <= floorIdx) floors.push(emptyRow());
  const row = floors[floorIdx];
  const free = row.indexOf(null);
  if (free !== -1) {
    row[free] = room;
    return;
  }
  const victimSlot = pickEarliest(row);
  const victim = row[victimSlot]!;
  row[victimSlot] = room;
  placeOn(floors, victim, floorIdx + 1);
}

/**
 * Fold one polled /runs roster into a Building.
 *
 * @param runs      the /runs roster (already polled)
 * @param prev      last tick's result — room stickiness (null on first tick)
 * @param dismissed failed run ids the user cleared from the incident hall;
 *                  an app whose *current* run is dismissed leaves the building
 *                  until its next run (a new failed run always re-flags)
 */
export function buildBuilding(
  runs: RunSummary[],
  prev: Building | null,
  dismissed: ReadonlySet<string>
): Building {
  const groups = groupApps(runs);

  const incidentHall: AppRoom[] = [];
  const seated = new Map<string, AppRoom>();
  for (const g of groups) {
    if (g.current.status === "error") {
      if (!dismissed.has(g.current.run_id)) incidentHall.push(toRoom(g));
      // dismissed → out of the building entirely until the app's next run
    } else {
      seated.set(g.appKey, toRoom(g));
    }
  }

  // 1. Stay put — surviving apps keep their exact {floor, room}, with fresh data.
  const floors: (AppRoom | null)[][] = [];
  const placed = new Set<string>();
  for (const f of prev?.floors ?? []) {
    const row = emptyRow();
    f.rooms.forEach((r, i) => {
      const fresh = r && seated.get(r.appKey);
      if (fresh) {
        row[i] = fresh;
        placed.add(r.appKey);
      }
    });
    floors.push(row);
  }
  if (!floors.length) floors.push(emptyRow());

  // 3+4. Seat new apps on the top floor, oldest first (so the newest is seated
  // last and stays top-floor under pressure); full floor → earliest descends.
  const fresh = [...seated.values()]
    .filter((r) => !placed.has(r.appKey))
    .sort((a, b) => a.startedAt - b.startedAt || a.appKey.localeCompare(b.appKey));
  for (const room of fresh) placeOn(floors, room, 0);

  // The building shrinks from the bottom when trailing floors empty out.
  while (floors.length > 1 && floors[floors.length - 1].every((r) => r === null))
    floors.pop();

  return {
    floors: floors.map((rooms, index) => ({ index, rooms })),
    incidentHall,
  };
}

/** Keep only dismissals whose run still exists — bounds localStorage by the live roster. */
export function pruneDismissed(
  dismissed: Iterable<string>,
  runs: RunSummary[]
): Set<string> {
  const alive = new Set(runs.map((r) => r.run_id));
  return new Set([...dismissed].filter((id) => alive.has(id)));
}
