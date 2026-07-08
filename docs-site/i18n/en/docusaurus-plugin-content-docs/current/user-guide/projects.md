---
title: "Projects"
description: "Group conversations around shared instructions and a dedicated knowledge base on the current main branch."
---

# Projects

A project groups related conversations around shared instructions and its own knowledge base. Any chat can be bound to a project, and the agent in that chat then receives the project instructions and, if configured, its knowledge base.

## What a project contains

| Field | Purpose |
|---|---|
| Name | The project name. Unique per user. |
| Description | An optional short note about the project. |
| Instructions | Optional text added to the system prompt in every project chat as extra context. |
| Knowledge base | An optional RAG collection bound to the project. |

## Project instructions

When a project has instructions, every bound chat injects them into the system prompt as a separate "Project context" block on top of the general system prompt. This is useful when a group of chats shares the same rules, role, or context.

Instructions apply only to chats bound to the project. Regular chats do not receive them.

## Project knowledge base

A project can have its own RAG collection. On project creation:

- if the user has [embeddings](./rag.md) configured, the project collection is created automatically;
- if embeddings are not configured, the project is saved without a knowledge base — you can add one later by configuring embeddings.

For RAG requirements, see [RAG over documents](./rag.md).

## How to use it

1. Create a project and optionally set its instructions.
2. Create a chat inside the project or bind an existing chat to it.
3. A project chip is shown above the input in such a chat.
4. The agent in that chat takes the project instructions and knowledge base into account.

In the sidebar, projects appear in a dedicated section with expandable folders; project chats are not duplicated in the main chat list.

:::note[Uploading files to a project]
Uploading files into a project knowledge base requires configured embeddings, and some flows also require a [sandbox](../operations/sandbox-security.md). When uploads are not possible, the UI explains what needs to be configured.
:::

## Main routes

With `giga_agent dev` the external prefix is `/api/agent`, so project routes are available under `/api/agent/projects`:

- `GET /projects` — list the user's projects;
- `POST /projects` — create a project;
- `GET /projects/{project_id}` — project details;
- `PATCH /projects/{project_id}` — update a project;
- `DELETE /projects/{project_id}` — delete a project.

The chat-to-project binding is stored in LangGraph thread metadata (`project_id`).
