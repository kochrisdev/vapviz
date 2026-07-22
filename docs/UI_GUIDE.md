# vapviz — UI Guide

A plain-language guide to reading your agent runs in the vapviz web app. No coding
knowledge needed. If you can open a web page, you can use this.

> Want to see it first? The **[live site](https://vapviz-website.vercel.app)** has a
> guided tour, screenshots, and a short demo video of everything below.

> **What is a "run"?** Every time you trace an AI agent, vapviz records it as a *run* —
> a timeline of everything the agent did: the questions it sent to the AI model, the
> tools it called, what came back, how long it took, and how much it cost.

---

## One app for everyone

There's no "beginner mode" to pick — everyone sees the same app, and depth is
opt-in where you need it. A run always opens on its plain-language **Story**;
the **Theater**, **Graph**, and **Logs** tabs sit right next to it when you
want to go deeper; and raw JSON stays tucked behind a *"Show technical
details"* link inside the detail panel until you ask for it. Nothing is
hidden, nothing is forced on you.

> The app wears vapviz's pixel-office look, end to end: chunky borders, square
> corners, pixel typefaces throughout, and a warm palette taken straight from
> the pixel office itself — so the app and its little animated scenes feel like
> one world, in both light and dark themes.

---

## Finding a run (the sidebar)

The left sidebar lists every run, newest first. Each entry shows:

- A **coloured dot** for status — green = finished, red = failed, amber (pulsing) = still running,
  grey = stopped by you (see *Pause, resume, stop* below).
- The run's **name**.
- A **one-line summary** of what happened, e.g.
  *"Weather agent answered 'What's the weather in Paris?' — 2 model calls (gpt-4o-mini),
  1 tool (get_temp), succeeded in 2.1 s, $0.000041."*

You can **search** runs (it also searches inside the steps), **tag** them, and **delete**
them with the buttons that appear when you hover.

---

## The Dashboard (the home screen)

When you first open the app you land on the **Dashboard** — an at-a-glance health view
across *all* your runs:

- **Runs · Running · Failed · Success rate** — the control-room numbers.
- **Total cost** and **average duration**.
- **Cost over time** chart and a **by-model** breakdown (which AI models you used, how
  many calls, and what they cost).

Click any run in the sidebar to leave the Dashboard and open that run. Click the chart
icon in the sidebar header to come back.

---

## Reading a run — the Story tab

Opening a run shows its **Story** — a summary card at the top, then a collapsible list of
what the agent did:

- The top box is the **agent** itself, with its status, total cost, and duration.
- Click a box to **expand** it and reveal the steps inside (and steps inside those).
- Each step shows a short, plain-language line of what it did, for example:
  - *"Asked gpt-4o-mini: 'What's the weather in Paris?'. It replied: '21°C and clear.'"*
  - *"Ran the tool get_temp with city=Paris → returned 'Paris: 21C, clear'."*

### Clicking a step → the detail panel

Click any step to open a panel on the right that explains **what happened** in plain
English, plus:

- **Status** and how long it took.
- **Tokens** used and the **cost** (for AI-model steps).
- The full **conversation** with the model, shown as chat bubbles (who said what).
- A **"Show technical details"** link — click it if you want to peek at the raw data
  behind the step.

Sensitive values like API keys are automatically hidden.

Press **Esc** to close the detail panel.

---

## Theater — watch your agents work

The **Theater** tab turns a run into a cozy pixel office — a tab at the top of every run.

- **Each agent is a little pixel worker** with its **name floating above its head**. The same
  agent always gets the same hair, shirt and skin colours, so you learn to recognise your cast —
  the nametag is what identifies who's who. Every agent also has its **own home desk** along the
  bottom of the room.
- **They walk to a station to work.** When an agent is talking to the AI model it walks to the
  **LLM desk**; when it runs a tool it heads for the station that matches the tool — the **SEARCH**
  bookshelves, the **FETCH** server racks, the **DATA** filing cabinet or the **PRINT** table. The
  active station glows, and a speech bubble says what the agent is up to ("phoning the API",
  "querying the DB", …). If something failed, the agent sits at its desk saying it **hit a snag**.
- **Watch it live or replay it.** For a run that's still going, the characters move in real time. For
  a finished run it opens calm (everyone at their desk); press **▶** in the bar at the bottom to
  replay from the start, or drag the slider to step through any moment.

> Multi-agent runs (a CrewAI crew, a LangGraph supervisor + workers) are where this shines — you can
> literally see which agent is doing what.

### Pause, resume, stop — the Agent control bar

While a run is **live**, the Theater tab shows an **Agent control** bar with **Pause** and
**Stop** buttons (it disappears once the run ends). This isn't just for show — it really controls
the agent:

- **Pause** asks the agent to hold on. Agents are polite, not instant: the bar says
  **"pausing…"** until the agent finishes the step it's on and actually parks, then
  **"paused"** with a **Resume** button. Think of asking a colleague to stop — they finish
  their sentence first. While paused, the office scene **dims and rests** with a **⏸ Paused**
  badge, so it's obvious the office is on a break rather than stuck.
- **Stop** ends the run at the agent's next opportunity. A stopped run gets a neutral grey
  **⏹ Stopped** badge — it didn't succeed and it didn't fail; *you* ended it — and it doesn't
  count against your success rate on the Dashboard.
- Every pause/resume/stop is written into the run's **Logs** ("Paused by user"), so the record
  stays honest.

### Talk to the agent — the Conversation panel

Beside the office scene, the Theater tab has a **chat panel** — a two-way conversation with the
running agent (it also stays as a read-only transcript after the run ends):

- **The agent can ask you a question.** When its code calls `vapviz.ask("Which region?")`, the
  question appears as a bubble, the reply box lights up ("type your answer…"), and the office
  rests with a **💬 Waiting for your input** badge. Type an answer and press send — the agent
  continues with it. Stop still works while it waits.
- **The agent can speak up on its own** (`vapviz.say(...)`) — e.g. to confirm it acted on
  something you sent — and those show as agent bubbles too.
- **You can steer any time** — type into the box even when the agent didn't ask; its code picks
  the message up with `vapviz.take_input()`. A message you've sent but the agent hasn't read yet
  shows as **"delivered — awaiting pickup"**.
- Every turn (the agent's questions/statements and your replies) is also written into the run's
  **Logs**, so the whole exchange stays on the record.

> This works for agents running in the same process as the vapviz server (like the demos).
> Agents that report over the network can't be controlled yet.

## The Office Building — monitor everything at once

Click the **🎭 masks icon** at the top of the sidebar for the **Office building**: every **app**
(pipeline) gets its own room, shown as **the same pixel office in miniature** — its own desks,
stations and walking workers (the tiny rooms skip the station labels and speech bubbles, but the
glow, the walking and the ✓ / ! name-tag marks still tell you what's happening). It's the
control-room view — glance at it to see all your agents working across all your apps.

How the building works:

- **A room belongs to an app, not a run.** Re-running an app lights the *same* room back up —
  the ×N badge counts its runs. (Give your pipeline a stable identity with
  `vapviz.trace("My app", app_id="my-app")`; without one, runs group by exact label.)
- **Each agent keeps its desk** across re-runs, so the room always looks familiar.
- **Floors hold six rooms** — two rows of three around a central **Walk Way**. When the top
  floor is full, the app that's been sitting there longest moves down a floor (still fully
  live and animating) — the building grows downward, new activity stays on top. You'll see a
  coworker **walk** the move: across the Walk Way, into the **Stairs**, then out of the
  **Door** on the floor below.
- **Every floor is drawn as a real place** — stone corridor tiles, shared walls with a door
  opening for every room, a runner rug and ceiling lights down the Walk Way, plants, a water
  cooler, a notice board, wall art and a clock. Each room's **nameplate** hangs on the wall by
  its door, with a status light. Empty rooms read as unlet offices.
- **The floor is alive while work runs** — a coworker steps out of any **running** room's door
  to mill on that floor's corridor, heading back inside when the app finishes. A walker on the
  corridor always means real work: exactly one per running room, nothing decorative. A quiet
  floor is an empty corridor. (No floor motion if your system is set to reduce motion.)
- **Failures gather in the Lounge** — the break room at the building's top-right. A failing
  app's room **stays where it is and turns red** (so you can't miss it), while its agents
  head up to the lounge to wait — each doing something different (coffee, vending machine,
  water cooler, lunch…). **Click its lounge card to inspect** the failed run, or press
  **Dismiss** to clear it until that app runs again (a *new* failure always re-flags, even
  after a dismissal — dismissals survive page reloads).
- **The lobby board** at the base keeps the live tally: apps working, agents in the lounge,
  spend today.
- **Click any room** to drop into that app's current run — it opens straight onto the
  **Theater** tab, so you land in the live office scene (with the control bar if it's running).
- **Control a room without leaving the floor** — hover a **running** room and small
  **Pause / Resume / Stop** buttons appear in its corner (the same cooperative control as the
  Theater bar). Talking to the agent (the conversation panel) stays on the Theater tab, where
  there's room to type.
- **A waiting agent flags itself** — if a running room's agent is blocked on `ask()` /
  `take_input()`, the room shows a **💬 needs input** badge you can't miss; click it to open the
  run in Theater and answer.

The sidebar mirrors the building: it lists **apps**, not individual runs — expand one (▸) to see
its full run history and click any past run to inspect and replay it.

---

## Going deeper — the Graph and Logs tabs

Next to Story and Theater, every run also has:

### Graph
A visual diagram (flow chart) of the run:

- **Node colour = what kind of step it is** — agent, step, tool, or AI-model call.
- **Border colour = status** — green finished, red failed, amber running.
- **Failed steps are loud** — filled red with a warning icon and a short error message.
- **Simplified / Detailed toggle** (top-right): *Simplified* (default) hides low-level
  framework "plumbing" so you see only the meaningful steps; *Detailed* shows every
  single node.
- Zoom, pan, and use the mini-map to navigate large runs. Click a node to open its detail.
- **Replay**: step through the run event-by-event to watch it build up as it happened.

### Logs
A clean, full-width table of every event in time order — timestamp, event type, and which
step it belongs to — with a filter box. Click a row to open that step's detail.

---

## Light and dark themes

The sun/moon button in the sidebar header switches between **light** and **dark** themes.
Your choice is remembered. Everything — including the graph — re-themes together.

---

## Exporting & sharing

The **Export** button (top-right of a run) lets you download the run as
**JSON** (the full data) or a **PNG** image of the graph — handy for sharing or attaching
to a report.

---

## Understanding the costs

Costs are shown to two significant figures so even tiny amounts are comparable
(e.g. `$0.000041` rather than just `<$0.0001`). A run's total cost is the sum of its
AI-model calls. `$0` means no billable model calls were recorded.

---

## Quick reference

| I want to… | Do this |
|------------|---------|
| See plain-language explanations | Open a run — it starts on **Story** |
| See the visual graph or raw event log | The **Graph** / **Logs** tabs |
| Understand one step | Click its box → read the detail panel |
| See the raw JSON for a step | Click **"Show technical details"** |
| Watch a run as a pixel "office" | Open the **Theater** tab |
| Pause / resume / stop a live run | The **Agent control** bar (Theater tab, while running) |
| Monitor all apps working at once | Open the **Office building** (🎭 masks icon, sidebar) |
| See an app's past runs | Expand the app in the sidebar (▸) → click a run |
| Clear a failed app from the building | **Dismiss** it in the lounge (returns on its next run) |
| Compare all runs at a glance | Open the **Dashboard** (chart icon, sidebar) |
| Hide framework plumbing in the graph | Use the **Simplified** toggle (Graph tab) |
| Watch a run play out | Use **Replay** (Graph tab) |
| Switch light/dark | Sun/moon button (sidebar) |
| Close the detail panel | Press **Esc** |
