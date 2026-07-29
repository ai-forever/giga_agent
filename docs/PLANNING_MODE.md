# Planning mode

Status: implemented · Scope: backend planning module + chat UI

## Model

Planning is split into two related workflows:

- **Normal mode:** `write_todo` maintains a lightweight execution checklist.
- **Plan mode:** `update_plan` maintains detailed Markdown plus a short todo
  checklist, and `present_plan()` pauses for user approval.

The graph remains the existing LLM → tools → LLM loop. Planning data is persisted
in `AgentState`:

```python
plan_content: str
todos: list[TodoItem]
todo_id_seq: int
plan_approved: bool
mode: Literal["normal", "plan"]
```

`TodoItem` contains `id`, `content`, `status`, and optional `note`. Status is one
of `pending`, `in_progress`, `completed`, or `cancelled`. Multiple items may be
`in_progress`.

## Todo identifiers

The backend owns todo identifiers:

- Creation omits `id`.
- Full replacement assigns `"1"` through `"N"` in argument order.
- Incremental creation assigns `todo_id_seq + 1`.
- Deletion never decrements the sequence or renumbers remaining items.
- An item with `id` is always a patch; an unknown id is an error.

All mixed updates are atomic. A failing patch changes neither the state nor the
sequence counter.

## Tools

### `write_todo(merge, todos)`

Available only in normal mode.

- `merge=false` replaces the list with at least two new items. IDs are forbidden.
- `merge=true` applies partial patches by id and may append items without id.
- An approved plan locks structure and content; only `status` and `note` patches
  to existing IDs are accepted.
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

The first Markdown value is initialized by replacing `""`. Later edits require
an exact unique match. Todo patches follow the same create-without-id and
update-with-id rules as `write_todo`; `remove_todo_ids` deletes draft items
without renumbering.

### `present_plan()`

Available only in plan mode and has no model-controlled arguments. It reads the
current state and requires non-empty Markdown plus at least two uniquely
identified `pending` todo items.

It interrupts with:

```json
{
  "type": "plan_approval",
  "plan_content": "...",
  "todos": []
}
```

Approve switches the same run to normal mode and locks the plan. Reject requires
feedback, keeps plan mode active, and returns the feedback to the model for
replanning. The approved ToolMessage persists a read-only UI snapshot:

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
- normal mode preserves the old todo but clears `plan_approved`.

An interrupt resume does not run the start-of-turn middleware, so a draft
survives approval or rejection.

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
