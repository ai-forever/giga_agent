---
title: "Local quickstart"
description: "Install and run GigaAgent 0.1.9."
---

# Local quickstart

:::info[Stable PyPI documentation]
This page describes the published PyPI package `giga-agent==0.1.9`. For the repository state, switch to version **main**.
:::

## Requirements

- Python 3.11 or newer; Python 3.12 is recommended.
- `uv` or `pip`.
- Free local port `9090`.

## Run

```bash
mkdir giga-agent-demo
cd giga-agent-demo
uv venv --python python3.12 .venv
source .venv/bin/activate
uv pip install "giga-agent[jupyter]==0.1.9"
giga_agent dev
```

Open `http://localhost:9090` and sign in as `admin@example.com` / `giga_agent_admin` for a local demo.
