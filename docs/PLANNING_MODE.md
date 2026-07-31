# Planning mode

Status: implemented · Scope: backend planning module + chat UI

## Model

Planning is split into two related workflows:

- **Normal mode:** `write_todo` maintains a lightweight execution checklist.
- **Plan mode:** `update_plan` maintains detailed Markdown plus a short todo
  checklist, and `present_plan()` pauses for user approval.

Plan mode does not require every conversational turn to produce a plan. The
agent may answer questions and discuss requirements normally. When the user
submits a task that implies later execution or a concrete change, the agent
researches it without side effects, asks material clarifying questions through
`ask_questions`, builds the draft, and finishes by calling `present_plan()`.

The graph remains the existing LLM → tools → LLM loop. Planning data is persisted
in `AgentState`:

```python
plan_content: str
todos: list[TodoItem]
todo_id_seq: int
plan_approved: bool
todos_editable: bool
mode: Literal["normal", "plan"]
```

`TodoItem` contains `id`, `content`, `status`, and optional `note`. Status is one
of `pending`, `in_progress`, `completed`, or `cancelled`. Multiple items may be
`in_progress`.

## Todo identifiers

Todo identifiers may be supplied by the caller or assigned by the backend:

- Creation accepts a unique, non-empty `id`; omitting it assigns the next numeric ID.
- Full replacement preserves supplied IDs and assigns numeric IDs to missing ones.
- Incremental creation with an unknown ID and `content` creates that item.
- Deletion never decrements the sequence or renumbers remaining items.
- An existing ID is a patch; an unknown ID without `content` is invalid.

All mixed updates are atomic. A failing patch changes neither the state nor the
sequence counter.

## Tools

### `write_todo(merge, todos)`

Available only in normal mode.

- `merge=false` replaces the list with at least two new items and accepts unique IDs.
- `merge=true` applies partial patches by existing ID and may create items with or
  without an ID.
- A plan approved with todo locks the list structure; existing items still
  accept `content`, `status`, and `note` patches. A todo list created after
  approving a plan without one remains editable.
- Empty lists do not clear old state.

The ToolMessage carries the complete result in
`additional_kwargs.planning`:

```json
{
  "type": "todo_snapshot",
  "todos": [],
  "assigned_ids": ["1", "2"]
}
```

### `update_plan(...)`

Available only in plan mode:

```text
find_string?: string
replace_string?: string
todos?: TodoPatch[]
remove_todo_ids?: string[]
```

The first Markdown value is initialized with `replace_string`; `find_string` is
optional while the plan is empty. Later edits require an exact unique match.
Todo patches follow the same create-without-id and
update-with-id rules as `write_todo`; `remove_todo_ids` deletes draft items
without renumbering.

### `present_plan()`

Available only in plan mode and has no model-controlled arguments. It reads the
current state and requires non-empty Markdown. Todo items are optional; when
present, they must have unique non-empty IDs and `pending` status.

It interrupts with:

```json
{
  "type": "plan_approval",
  "plan_content": "...",
  "todos": []
}
```

Approve switches the same run to normal mode and locks the plan. If the approved
plan has no todo, `todos_editable` remains true: the agent may later create and
change its working todo list without changing the approved Markdown plan. Reject
requires feedback, keeps plan mode active, and returns the feedback to the model
for replanning. The approved ToolMessage persists a read-only UI snapshot:

```json
{
  "type": "approved_plan",
  "plan_content": "...",
  "todos": []
}
```

## Lifecycle and gating

At the start of a new user turn:

- plan mode starts with empty planning state and sequence zero;
- normal mode preserves the old todo but clears `plan_approved` and
  `todos_editable`.

An interrupt resume does not run the start-of-turn middleware, so a draft
survives approval or rejection.

In plan mode, `PlanningModule.get_instructions()` returns no prompt fragment.
`BaseAgent.get_prompt()` appends the plan-mode instructions once at the end of
the main system prompt, immediately before the user's `contextInstructions`.
This keeps the active-mode contract close to the model input without duplicating
it among module prompts.

Tool visibility:

| Mode | Available planning tools |
|---|---|
| normal | `write_todo` |
| plan | `update_plan`, `present_plan` |

The tools also validate `state["mode"]` themselves, so direct or stale calls
cannot bypass model-binding filters.

## UI

- Draft `update_plan` calls are hidden.
- The latest `write_todo` call renders its complete `todo_snapshot`.
- `present_plan` renders Markdown and todo items with Approve and Reject actions.
- Reject requires non-empty feedback.
- After approval, an immutable plan card remains in message history.
