---
title: "Local quickstart"
description: "Install and run GigaAgent 0.1.9."
---

# Local quickstart

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
