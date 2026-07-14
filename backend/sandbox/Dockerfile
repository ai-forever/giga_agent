FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

USER root
WORKDIR /root

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=true \
    JUPYTER_CONFIG_PATH=/root/.jupyter \
    IPYTHON_CONFIG_PATH=/root/.ipython \
    SERVER_PATH=/root/.server \
    BUN_INSTALL=/root/.bun \
    PNPM_HOME=/root/.local/share/pnpm \
    PATH=/root/.bun/bin:/root/.local/share/pnpm:$PATH

# System dependencies
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive DEBCONF_NOWARNINGS=yes apt-get install -y \
    build-essential \
    curl \
    git \
    util-linux \
    jq \
    sudo \
    fonts-noto-cjk \
    fonts-liberation \
    fonts-noto-color-emoji \
    ca-certificates \
    s3fs \
    wget \
    unzip \
    zip \
    xz-utils \
    procps \
    ripgrep \
    fd-find \
    less \
    tree \
    lsof \
    netcat-openbsd \
    dnsutils \
    openssh-client \
    ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Chromium for headless rendering (Hyperframes / Puppeteer)
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive DEBCONF_NOWARNINGS=yes apt-get install -y --no-install-recommends \
    chromium && \
    rm -rf /var/lib/apt/lists/*

RUN printf '#!/bin/sh\nexec /usr/bin/chromium --no-sandbox --disable-dev-shm-usage "$@"\n' \
        > /usr/local/bin/chromium-headless && \
    chmod +x /usr/local/bin/chromium-headless

ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-headless

# Node.js + pnpm
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive DEBCONF_NOWARNINGS=yes apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    corepack enable && \
    corepack prepare pnpm@latest --activate

# Bun
RUN curl -fsSL https://bun.sh/install | bash && \
    ln -s /root/.bun/bin/bun /usr/local/bin/bun && \
    ln -s /root/.bun/bin/bunx /usr/local/bin/bunx

# Python dependencies
COPY requirements.txt requirements.txt
RUN uv pip install --no-cache -r requirements.txt
RUN ipython kernel install --name 'python3' --user

# Bash kernel
RUN uv pip install --no-cache bash_kernel
RUN python -m bash_kernel.install

# Configuration files
COPY matplotlibrc .config/matplotlib/.matplotlibrc
COPY jupyter_server_config.py .jupyter/
RUN mkdir -p .ipython/profile_default/startup
COPY ipython_kernel_config.py .ipython/profile_default/
COPY startup_scripts .ipython/profile_default/startup

# SandboxAPI Server (in-guest agent). Additive: не меняем CMD/ENTRYPOINT, чтобы
# существующие рантаймы (local_docker: `sleep infinity` + ленивый jupyter; e2b)
# продолжали работать. Сервер запускается по требованию: `sandbox-server`.
COPY server/requirements.txt /root/.server/sandbox_server/requirements.txt
RUN uv pip install --no-cache -r /root/.server/sandbox_server/requirements.txt
COPY server/ /root/.server/sandbox_server/
COPY VERSION /root/.server/VERSION
ENV PYTHONPATH=/root/.server
RUN printf '#!/bin/sh\nexec python -m sandbox_server "$@"\n' \
        > /usr/local/bin/sandbox-server && \
    chmod +x /usr/local/bin/sandbox-server
# Supervisor: respawn the server if it crashes (совместимо с docker --rm,
# в отличие от restart_policy). PID 1 — этот крошечный loop, поэтому при OOM
# ядро скорее прибьёт тяжёлый kernel/пользовательский процесс, а не сервер.
RUN printf '#!/bin/sh\nwhile true; do\n  sandbox-server\n  echo "[supervisor] sandbox-server exited ($?); restarting in 1s" >&2\n  sleep 1\ndone\n' \
        > /usr/local/bin/sandbox-server-supervised && \
    chmod +x /usr/local/bin/sandbox-server-supervised

RUN useradd -m user
RUN mkdir -p /home/user
RUN chown -R user:user /home/user