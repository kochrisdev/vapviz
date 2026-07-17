import { useLayoutEffect, useRef } from "react";
import { drawFloorEnv, type EnvRoom, type Rect } from "../lib/floorArt";

/**
 * The per-floor environment canvas (Phase 4d, UI-ROADMAP §4-L) — rendered as
 * the first child of a `.vt-floor`, absolutely positioned under the rooms. It
 * measures its parent floor's cells (rooms, Walk Way, Door/Stairs, east wall)
 * and hands the floor-local rects to the pure `drawFloorEnv`. Redraws on
 * layout resize and whenever `sig` (the floor's occupancy signature) changes.
 */
export function FloorEnv({ sig }: { sig: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useLayoutEffect(() => {
    const cv = ref.current;
    const floor = cv?.parentElement;
    if (!cv || !floor) return;

    const draw = () => {
      const fb = floor.getBoundingClientRect();
      if (fb.width < 4 || fb.height < 4) return;
      const dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(fb.width * dpr);
      cv.height = Math.round(fb.height * dpr);
      cv.style.width = `${fb.width}px`;
      cv.style.height = `${fb.height}px`;

      const rel = (r: DOMRect): Rect => ({
        x: r.left - fb.left,
        y: r.top - fb.top,
        w: r.width,
        h: r.height,
      });
      const q = (sel: string): Rect | null => {
        const el = floor.querySelector(sel);
        return el ? rel(el.getBoundingClientRect()) : null;
      };

      const rooms: EnvRoom[] = [];
      floor.querySelectorAll<HTMLElement>(".vt-room").forEach((el) => {
        const rect = rel(el.getBoundingClientRect());
        const door = el.querySelector(".vt-room-door");
        const doorSide: "top" | "bottom" = door
          ? door.classList.contains("vt-room-door--top")
            ? "top"
            : "bottom"
          : el.dataset.doorside === "top"
            ? "top"
            : "bottom";
        const doorRect = door ? rel(door.getBoundingClientRect()) : null;
        const doorCx = doorRect ? doorRect.x + doorRect.w / 2 : rect.x + rect.w / 2;
        rooms.push({ rect, doorCx, doorSide, occupied: !!el.dataset.appkey });
      });

      drawFloorEnv(cv.getContext("2d")!, {
        w: fb.width,
        h: fb.height,
        rooms,
        walk: q(".vt-walkway"),
        door: q(".vt-door"),
        stairs: q(".vt-stairs"),
        east: q(".vt-eastwall"),
      }, dpr);
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(floor);
    return () => ro.disconnect();
  }, [sig]);

  return <canvas ref={ref} className="vt-floor-env sprite" aria-hidden="true" />;
}
