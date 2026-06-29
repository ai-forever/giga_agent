# Planning Mode — Design Doc

Status: **Draft** · Scope: backend (`core/agent`, new `modules/planning`) + frontend (chat UI)

## Goal

Let the agent decompose a multi-step request into an explicit todo list and work
through it, with the list visible and live-updating in the UI. For requests with
side effects, the agent first proposes a plan and waits for the user to approve,
edit, or reject it.

This is **not** a separate planner/executor subgraph. The model maintains its own
todo list via a tool; the graph stays the single LLM→tools→LLM loop it is today.
Rationale: a dedicated planner harness is exactly the kind of brittle, model-
generation-specific machinery that ages badly (see the "Managed Agents" reasoning —
keep the harness thin, let the model plan).

## Decisions (locked)

| Decision | Choice | Why |
|----------|--------|-----|
| Execution style | **Dynamic todo list** (Claude Code `TodoWrite` style) | Minimal graph change; flexible replanning; model is capable enough to self-manage |
| Approval gate | **Plan mode with a pause** (LangGraph `interrupt`) | Safe for side-effecting requests; user keeps control before execution |
| Gate mechanism | **Tool `present_plan` that calls `interrupt()`** | Logic stays in the planning module (cohesion); model signals "plan ready" naturally |
| Persistence | **In graph state** (`AgentState`, via checkpointer) | Zero new tables/API; survives restarts by `thread_id` |
| Delivery | **Single PR** (todo + plan mode + gate + tests) | Cohesive change; one review cycle |

## Verified against code (eng review)

Five load-bearing assumptions were checked against the actual codebase:

| Assumption | Verdict | Evidence |
|-----------|---------|----------|
| Graph loops LLM→tools→LLM, so a tool can flip `mode` and the next LLM call sees it in the same turn | **YES** | `graph_factory.py:780-794`, `:281-282`; recursion limit 10k |
| Tools may return `Command(update={...})` to mutate `AgentState` | **YES** (already used by the `python` tool for `kernel_id`) | `tool_node.py:693-695`, `:946-1016` |
| Checkpointer + `interrupt()` + `Command(resume=...)` already wired | **YES** — HITL tool approval already does this | `middlewares/tool_result.py:447`, `cli_chat.py:711`, served by LangGraph Server (`langgraph.json`) |
| Tool filtering can gate on `state["mode"]` | **PARTIAL** — existing `_disabled_module_ids` reads config only; state-gating is a few new lines in `amodel_node` | `graph_factory.py:630-643`, `base.py:55-75` |
| A new `plan` state field reaches the frontend automatically | **NO** — chat streams `stream_mode="messages"`; must `push_ui_message` explicitly | `deep_research/graph.py:98-124` |

Net: the risky part (interrupt/resume approval) is already de-risked by existing
machinery. The two real work items the review surfaced are folded into the design
below: **state-based tool gating** (not config) and **explicit UI push** for the plan.

## Lifecycle

```
                   plan mode ON (user toggle in composer)
                            │
   user msg ──► [prompt build] ── mode=plan ──► tool filter: read-only only
                            │                    (search/rag/scraper); side effects off
                            ▼
                   agent researches, builds a plan
                            │
                            ▼
                  present_plan(todos) ──► interrupt()  ◄─── PAUSE, plan shown in UI
                            │
          ┌─────────────────┼──────────────────┐
       Approve            Edit               Reject + feedback
          │                 │                     │
   mode=normal,      mode=normal,          stays mode=plan,
   plan=approved     plan=edited           feedback as new user msg
          └─────────────────┴─────► [execution] ◄──── re-plan
                                         │
                              all tools enabled; agent walks the list;
                              update_plan flips statuses
                              (exactly one in_progress)
```

In `normal` mode (plan toggle off) the agent simply uses `update_plan` when a
request is non-trivial; there is no pause.

## Backend

### State — `core/agent/types.py`

```python
class TodoItem(TypedDict):
    id: str
    title: str
    status: Literal["pending", "in_progress", "completed", "skipped"]
    note: NotRequired[str]          # short result, or reason for skip

class AgentState(TypedDict):
    ...
    plan: NotRequired[list[TodoItem]]                # default reducer = replace
    mode: NotRequired[Literal["normal", "plan"]]     # seeded from config at turn start
    plan_approved: NotRequired[bool]                 # internal gate flag
```

- `plan` lives in `AgentState` → persisted by the existing checkpointer per
  `thread_id`. No new tables.
- `mode` is copied from `config.configurable.plan_mode` at the start of a turn
  **only if not already set in state**, so the user's toggle and the agent's
  internal "awaiting approval" state don't fight.

### New module — `modules/planning/`

Standard `BaseModule`. Exposes two tools and instructions; no API router needed
for v1 (state streams over the existing channel).

**`update_plan(todos)`** — the workhorse. State-mutating, returns a `Command`:

```python
@tool
async def update_plan(todos: list[TodoItem]) -> Command:
    _validate_single_in_progress(todos)          # invariant: ≤1 in_progress
    return Command(update={
        "plan": todos,
        "messages": [ToolMessage("Plan updated", tool_call_id=...)],
    })
```

`tool_node.py` already injects state into tools and handles `Command` — no extra
graph node. **Hard requirement** (`tool_node.py:1000`): the `update` dict MUST
include a `ToolMessage` whose `tool_call_id` matches this call, or the node raises
`ValueError`. Both tools below satisfy this.

**`present_plan(todos)`** — plan mode only. Pauses via `interrupt()` and resolves
the gate from the resume payload:

```python
@tool
async def present_plan(todos: list[TodoItem]) -> Command:
    decision = interrupt({"type": "plan_review", "plan": todos})   # PAUSE
    if decision["action"] == "approve":
        return Command(update={
            "plan": decision.get("plan", todos),   # edited list if user edited
            "mode": "normal",
            "plan_approved": True,
            "messages": [ToolMessage("Plan approved", tool_call_id=...)],
        })
    # reject: feedback becomes a user message; stay in plan mode and re-plan
    return Command(update={
        "messages": [HumanMessage(decision["feedback"])],
    })
```

`interrupt()` relies on the existing checkpointer. Resume is
`Command(resume={...})` issued by the API when the user clicks a button.

### Tool gating in plan mode

**Must gate on `state["mode"]`, not on config.** The existing filter
`_disabled_module_ids` (`base.py:55-75`) reads only `config.configurable`, which is
fixed for the whole run. But `present_plan`'s approval flips `mode` to `normal` and
resumes the *same* run, so the tool set has to change mid-turn — config can't do
that. This is new code (a few lines), not reuse of the existing filter.

The tool list is rebuilt on every entry to `amodel_node`, so add the gate there
(`graph_factory.py:630-643`, where `all_tools` is assembled — `state` is in scope):

```python
if state.get("mode") == "plan":
    all_tools = [t for t in all_tools
                 if t.name in READ_ONLY_TOOLS | {"present_plan", "update_plan"}]
```

`READ_ONLY_TOOLS` = search, scraper, rag, analyze_images. Disabled in plan mode:
repl write, io, github/vk posting, image generation. The agent can research before
proposing, but cannot cause side effects. Because the loop returns to `amodel_node`
after every tool batch (verified: `graph_factory.py:780-794`), the flip to `normal`
re-enables the full tool set for the very next LLM call, in the same turn.

### Prompt — `get_instructions()`

- **normal:** "For requests of 3+ non-trivial steps, call `update_plan` first.
  Keep exactly one item `in_progress`. Update statuses immediately as each step
  finishes — not in batches. If reality diverges from the plan, rewrite the list;
  don't pretend it still holds."
- **plan:** "You are in planning mode. Use only read-only tools to research. Do
  not perform side effects. When done, call `present_plan` with the final task
  list and wait for the decision."
- Cross-turn hygiene: "On a new, unrelated request, clear the old plan with
  `update_plan([])`."

## Frontend

- **Streaming (corrected):** a new `plan` field in `AgentState` does NOT reach the
  UI on its own — the chat consumes `stream_mode="messages"` (tokens), not
  `"values"`. Push it explicitly the way `deep_research` does
  (`deep_research/graph.py:98-124`): `push_ui_message("plan_update", {"plan": todos})`
  from the planning module on each update. Reuse the existing custom-UI stream
  channel (and, if possible, the deep_research plan-render component) rather than
  adding a new transport.
- **Checklist:** live component — spinner on `in_progress`, check on `completed`,
  strikethrough on `skipped`.
- **Approval gate:** on an `interrupt` of type `plan_review`, render a plan card
  with **Approve / Edit / Reject**. Edit = inline todo editing; Reject = feedback
  textarea. The button resolves the interrupt via the resume endpoint.
- **Plan-mode toggle** in the composer (like Claude Code), sends
  `config.configurable.plan_mode`.

## Test plan

```
[+] modules/planning/tools.py
  ├── update_plan()
  │   ├── valid list            → Command with plan + matching ToolMessage
  │   ├── two in_progress       → validation error (single-in_progress invariant)
  │   └── empty list            → clears plan (cross-turn hygiene)
  └── present_plan() + interrupt
      ├── [→E2E] approve        → mode=normal, execution continues in same run
      ├── [→E2E] edit           → plan replaced with edited list, then execute
      └── [→E2E] reject+feedback → stays mode=plan, feedback becomes user msg, re-plan
[+] graph_factory.amodel_node
      └── mode=plan             → side-effecting tools filtered out, read-only kept
[+] frontend
      └── plan_update UI message → checklist renders; in_progress shows spinner
```

3 E2E paths exercise the real interrupt/resume contract (approve/edit/reject); the
rest are unit tests. The interrupt tests are the critical ones — they prove the
gate actually pauses and resumes correctly against the checkpointer.

## Open questions / risks

- **Auto-enter plan mode.** Should the agent enter plan mode itself for "risky"
  requests, beyond the manual toggle? v1: manual toggle only — don't guess.
- **Replanning.** No dedicated replan node; the agent re-calls `update_plan`. The
  prompt must explicitly license rewriting the list.
- **Mode flip mid-turn — RESOLVED.** Verified the graph loops LLM→tools→LLM
  (`graph_factory.py:780-794`, ends only when the AIMessage has no tool calls), so
  a `Command`-driven flip to `normal` is seen by the next LLM call in the same turn.
- **Resume plumbing — RESOLVED.** The chat path already resumes via
  `Command(resume=...)` (`cli_chat.py:711`); plan approval reuses it with a new
  payload type `{"type": "plan_approval"}`, mirroring `tool_result.py:447`.
- **Plan across turns.** The plan persists in state; a new message sees the old
  checklist. Cross-turn hygiene rule (above) handles staleness.

## Out of scope (v1)

- Dedicated `PlanModel` table + REST/WS plan API + standalone "Tasks" panel.
- Nested / hierarchical subtasks.
- Per-task tool restrictions.
