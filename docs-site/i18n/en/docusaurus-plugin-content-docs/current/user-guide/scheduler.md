---
title: "Scheduled tasks"
description: "Deferred and recurring background tasks of the agent."
---

# Scheduled tasks

The agent runs tasks in the background on a schedule: once at a given time ("tomorrow at 9, prepare a weather summary") or periodically ("collect weekly results every Monday"). A task is phrased as an ordinary chat request — the agent calls the right tool itself and confirms the scheduling.

## Creating a task

Tell the agent what to run and when. Time is given as a date ("June 29 at 9:00") or a recurrence ("every day at 9"); internally these become one-off tasks with a run date and periodic tasks with a cron schedule. A task can carry a short name.

The result arrives as a message in a connected [channel](./channels.md) — for example, your Telegram. Recipients can be picked at scheduling time from the approved channel contacts; without an explicit choice the result goes to the default recipients. If the task owner has no recipients at all, the task completes with nowhere to deliver — connect a channel beforehand.

## Managing tasks

The task list is available in two places:

- in the web UI — the **Scheduler** item in the user menu opens the **Scheduled tasks** page, where tasks can be reviewed and deleted;
- in chat — ask the agent to list, edit, or cancel tasks. The task text, time, name, and recipients can be changed.

In a Telegram group chat, tasks follow the chat's rules: a task created in the chat delivers its result to that same chat, and only its author can edit or cancel it.

## What a task can do

A background task is a full agent run with your text: it can search, compute, and use connected services. The task inherits the memory scope of the conversation where it was created, so the agent in the background remembers the context available to that conversation.
