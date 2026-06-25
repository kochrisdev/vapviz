/**
 * Pixel-character avatar engine for the Theater view (UI-ROADMAP Phase 3).
 *
 * Each agent gets a little full-body pixel character built from swappable parts
 * (skin / hair / outfit / accessory / kind), assembled *deterministically* from
 * the agent's name — so the same agent keeps its costume across runs. Identity
 * is carried by the floating nametag in the view; the character just needs to be
 * distinct-ish and have personality.
 *
 * Pure + offline + zero-dependency: returns an SVG string (14×20 pixel grid,
 * `shape-rendering: crispEdges`). Characters are full-colour; the room/UI around
 * them is themed from the vapviz design tokens. Token-derived colours (eyes,
 * status ring, bubble) are read at call time, so regenerate on theme change.
 *
 * This is the one place that knows how a face is made — the Theater view only
 * ever calls `agentSprite(name, state)`, so the art is swappable later.
 */

export type AvatarState = "idle" | "thinking" | "working" | "done" | "error";

interface Parts {
  skin: number;
  hair: number;
  style: number;
  cloth: number;
  pant: number;
  species: number; // 0 human, 1 robot, 2 alien
  acc: string; // none | glasses | headphones | cap
}

// Characters are full-colour; UI/room uses vapviz tokens.
const SKIN = ["#F2C9A0", "#E7B58B", "#C68A5E", "#9C6638", "#6E4327"];
const HAIRC = ["#23211F", "#5A3A22", "#C9A227", "#E8E6E1", "#8B2E2E", "#3A6EA5", "#7A3FA0", "#D96B3A"];
const CLOTH = ["#6366F1", "#38BDF8", "#34D399", "#C084FC", "#F59E0B", "#FB7185", "#2DD4BF", "#A3E635", "#94A3B8"];
const PANT = ["#2E3440", "#5A4632", "#28324A", "#3B3B3B", "#4B5563"];
const HAIRSTYLE = ["short", "long", "spiky", "bun"];
const ACC = ["none", "glasses", "headphones", "cap"];

// Best-effort role → accessory (silent when nothing matches).
const ROLES: [RegExp, string][] = [
  [/research|investig|analy|search|retriev|lookup|index/i, "glasses"],
  [/code|dev|engineer|program/i, "headphones"],
  [/plan|orchestr|superv|coordinat|manage|route|router/i, "cap"],
];
function accForRole(name: string): string | null {
  for (const [re, a] of ROLES) if (re.test(name)) return a;
  return null;
}

// FNV-1a 32-bit — stable across runs/sessions.
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h >>> 0;
}
const pick = (h: number, s: number, m: number) => (h >>> s) % m;

export function agentParts(name: string): Parts {
  const h = hash(name || "agent");
  const sp = pick(h, 24, 6);
  const species = sp === 0 ? 1 : sp === 1 ? 2 : 0; // ~17% robot, ~17% alien, rest human
  const roleAcc = accForRole(name);
  return {
    skin: pick(h, 0, SKIN.length),
    hair: pick(h, 3, HAIRC.length),
    style: pick(h, 7, HAIRSTYLE.length),
    cloth: pick(h, 10, CLOTH.length),
    pant: pick(h, 14, PANT.length),
    species,
    acc: roleAcc || ACC[pick(h, 18, ACC.length)],
  };
}

function hex2rgb(x: string): [number, number, number] {
  return [parseInt(x.slice(1, 3), 16), parseInt(x.slice(3, 5), 16), parseInt(x.slice(5, 7), 16)];
}
function mix(a: string, b: string, t: number): string {
  const A = hex2rgb(a), B = hex2rgb(b);
  return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
}
function tok(name: string): string {
  if (typeof window === "undefined") return "#000000";
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? `rgb(${v})` : "#000000";
}

function stateStyle(s: AvatarState): { eye: string; ring: string | null; cue: "think" | "x" | null } {
  switch (s) {
    case "thinking": return { eye: tok("--kind-llm"), ring: "--status-running", cue: "think" };
    case "working": return { eye: tok("--kind-tool"), ring: "--status-running", cue: null };
    case "done": return { eye: tok("--status-success"), ring: "--status-success", cue: null };
    case "error": return { eye: tok("--status-error"), ring: "--status-error", cue: "x" };
    default: return { eye: "#1B2433", ring: null, cue: null };
  }
}

/** A pixel character for `name` in a given activity `state`. Returns SVG markup. */
export function agentSprite(name: string, state: AvatarState = "idle", ov: Partial<Parts> | null = null): string {
  const p = ov ? { ...agentParts(name), ...ov } : agentParts(name);
  const st = stateStyle(state);
  const skin = SKIN[p.skin], hairc = HAIRC[p.hair], cloth = CLOTH[p.cloth];
  const clothD = mix(cloth, "#000000", 0.22), pant = PANT[p.pant], boot = mix(pant, "#000000", 0.3);
  const faceC = p.species === 1 ? "#A6B0BE" : p.species === 2 ? "#86C98A" : skin;
  const faceD = mix(faceC, "#000000", 0.18);
  const A: string[] = [];
  const add = (x: number, y: number, c: string, w = 1, h = 1) => { if (c) A.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`); };

  // head / face (cols 4..9, rows 3..7)
  add(4, 3, faceC, 6, 5);
  add(4, 8, faceC, 6, 1);
  add(4, 7, faceD, 6, 1);

  // hair / headgear
  if (p.species === 0) {
    if (p.acc !== "cap") {
      add(4, 2, hairc, 6, 1); add(3, 3, hairc, 1, 2); add(10, 3, hairc, 1, 2);
      if (p.style === 0) { add(4, 3, hairc, 6, 1); }
      else if (p.style === 1) { add(4, 3, hairc, 6, 1); add(3, 3, hairc, 1, 5); add(10, 3, hairc, 1, 5); }
      else if (p.style === 2) { add(4, 1, hairc, 1, 1); add(6, 1, hairc, 1, 1); add(8, 1, hairc, 1, 1); add(4, 2, hairc, 6, 1); }
      else { add(4, 3, hairc, 6, 1); add(6, 0, hairc, 2, 2); }
    }
  } else if (p.species === 1) {
    add(4, 2, mix(faceC, "#000000", 0.25), 6, 1); add(6, 0, tok("--accent"), 1, 2);
    add(3, 5, mix(faceC, "#000000", 0.3), 1, 1); add(10, 5, mix(faceC, "#000000", 0.3), 1, 1);
  } else {
    add(4, 2, faceC, 6, 1); add(4, 1, faceD, 1, 1); add(9, 1, faceD, 1, 1);
  }

  // eyes + glasses / cap / headphones
  const eyeC = st.eye;
  if (p.species === 2) { add(5, 5, "#10151F", 2, 1); add(8, 5, "#10151F", 2, 1); add(5, 5, eyeC); add(8, 5, eyeC); }
  else { add(5, 5, eyeC); add(8, 5, eyeC); }
  if (p.acc === "glasses") {
    add(4, 5, "#101418"); add(6, 5, "#101418"); add(7, 5, "#101418"); add(9, 5, "#101418");
    add(5, 5, "#E6F0FF"); add(8, 5, "#E6F0FF");
  }
  if (p.acc === "cap") { add(4, 2, tok("--accent-hover"), 6, 1); add(3, 3, tok("--accent-hover"), 5, 1); }
  if (p.acc === "headphones") { add(3, 4, tok("--accent"), 1, 3); add(10, 4, tok("--accent"), 1, 3); add(4, 2, tok("--accent"), 6, 1); }

  // torso + arms
  add(3, 9, cloth, 8, 4); add(3, 13, clothD, 8, 1); add(6, 9, clothD, 2, 1);
  add(2, 9, cloth, 1, 3); add(11, 9, cloth, 1, 3); add(2, 12, faceC, 1, 1); add(11, 12, faceC, 1, 1);

  // legs: two frame groups (A = stand, B = step) — view toggles via CSS when walking
  const legA: string[] = [], legB: string[] = [];
  const leg = (arr: string[], x: number, y: number, h: number) => arr.push(`<rect x="${x}" y="${y}" width="2" height="${h}" fill="${pant}"/>`);
  const foot = (arr: string[], x: number, y: number) => arr.push(`<rect x="${x}" y="${y}" width="2" height="1" fill="${boot}"/>`);
  leg(legA, 4, 14, 4); foot(legA, 4, 18); leg(legA, 8, 14, 4); foot(legA, 8, 18);
  leg(legB, 4, 14, 3); foot(legB, 4, 17); leg(legB, 8, 14, 4); foot(legB, 8, 18);

  const ring = st.ring
    ? `<g fill="none" stroke="${tok(st.ring)}" stroke-width="0.6"><rect x="1.5" y="0.5" width="11" height="19" rx="1.5"/></g>`
    : "";

  return `<svg class="sprite" viewBox="0 0 14 20" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${name}">`
    + `<g>${A.join("")}</g><g class="legA">${legA.join("")}</g><g class="legB">${legB.join("")}</g>${ring}</svg>`;
}

/** Small pixel thought-bubble, shown above a thinking character. Returns SVG markup. */
export function thoughtBubble(): string {
  const llm = tok("--kind-llm"), surf = tok("--surface");
  return `<svg class="bubble sprite" width="22" height="18" viewBox="0 0 11 9" shape-rendering="crispEdges">`
    + `<rect x="1" y="0" width="9" height="6" rx="1" fill="${surf}" stroke="${llm}" stroke-width=".6"/>`
    + `<rect x="3" y="2" width="1" height="1" fill="${llm}"/><rect x="5" y="2" width="1" height="1" fill="${llm}"/><rect x="7" y="2" width="1" height="1" fill="${llm}"/>`
    + `<rect x="2" y="7" width="1" height="1" fill="${surf}" stroke="${llm}" stroke-width=".4"/></svg>`;
}
