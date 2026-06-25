# vapviz — UI Guide

A plain-language guide to reading your agent runs in the vapviz web app. No coding
knowledge needed. If you can open a web page, you can use this.

> **What is a "run"?** Every time you trace an AI agent, vapviz records it as a *run* —
> a timeline of everything the agent did: the questions it sent to the AI model, the
> tools it called, what came back, how long it took, and how much it cost.

---

## The two modes: Simple and Technical

At the top-left of the app there's a switch:

| Mode | Who it's for | What you see |
|------|--------------|--------------|
| **Simple** *(default)* | Anyone — PMs, support, stakeholders | A plain-language story of the run. Each step explained in words. |
| **Technical** | Developers / debugging | Everything in Simple **plus** the visual graph, the raw event log, and the underlying JSON data. |

Your choice is remembered the next time you open the app. Switching modes never changes
your data — it only changes how much detail is shown.

---

## Finding a run (the sidebar)

The left sidebar lists every run, newest first. Each entry shows:

- A **coloured dot** for status — green = finished, red = failed, amber (pulsing) = still running.
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

## Reading a run in Simple mode

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
  behind the step. (In Technical mode this is always shown.)

Sensitive values like API keys are automatically hidden.

Press **Esc** to close the detail panel.

---

## Theater — watch your agents work

The **Theater** tab turns a run into a little pixel "office". It's available in **both Simple and
Technical** modes (it's meant for everyone), as a tab at the top of a run.

- **Each agent is a character** with its **name floating above its head**. The same agent always
  gets the same character, so you learn to recognise your cast. Robots, people, the occasional
  alien — it's just for personality; the nametag is what identifies who's who.
- **They walk to a desk to work.** When an agent is talking to the AI model it walks to the **LLM
  desk** (a thought bubble pops up); when it runs a tool it goes to the **tool bench**. The desk
  lights up while it's in use. When it's done it rests; if it failed, it turns **red**.
- **Watch it live or replay it.** For a run that's still going, the characters move in real time. For
  a finished run it opens calm (everyone resting); press **▶** in the bar at the bottom to replay
  from the start, or drag the slider to step through any moment.

> Multi-agent runs (a CrewAI crew, a LangGraph supervisor + workers) are where this shines — you can
> literally see which agent is doing what.

## The Live Floor — monitor everything at once

Click the **🎭 masks icon** at the top of the sidebar for the **Live floor**: one open office floor
showing **every active and recent run at once**, each as its own softly-labelled area with its own
desks and walking characters. It's the control-room view — glance at it to see all your agents working
across all your runs simultaneously, who's busy, and which run (if any) has gone red. **Click any run's
area** to drop into that run's full Theater.

---

## Technical mode extras

Switching to **Technical** keeps everything above and adds the **Graph** and **Logs** tabs (on top of
Story and Theater):

### Story
The same narrative as Simple mode.

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

In Technical mode, the **Export** button (top-right of a run) lets you download the run as
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
| See plain-language explanations | Stay in **Simple** mode |
| See the visual graph or raw data | Switch to **Technical** mode |
| Understand one step | Click its box → read the detail panel |
| See the raw JSON for a step | Click **"Show technical details"** |
| Watch a run as a pixel "office" | Open the **Theater** tab (any mode) |
| Monitor all runs working at once | Open the **Live floor** (🎭 masks icon, sidebar) |
| Compare all runs at a glance | Open the **Dashboard** (chart icon, sidebar) |
| Hide framework plumbing in the graph | Use the **Simplified** toggle (Graph tab) |
| Watch a run play out | Use **Replay** (Graph tab) |
| Switch light/dark | Sun/moon button (sidebar) |
| Close the detail panel | Press **Esc** |
