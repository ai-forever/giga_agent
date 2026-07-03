"""Sidecar socat proxy for exposing sandbox ports to localhost."""

import asyncio
import re
import time
import uuid
from typing import Any

from docker.errors import DockerException, NotFound

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.sandbox.local_docker.constants import (
    CLOUDFLARED_IMAGE,
    MANAGED_LABEL,
    PROXY_KIND_LABEL,
    PROXY_KIND_SOCAT,
    PROXY_KIND_TUNNEL,
    PROXY_LABEL,
    PROXY_PORT_LABEL,
    SANDBOX_ID_LABEL,
    SOCAT_IMAGE,
)

logger = get_logger(__name__)

# cloudflared quick-tunnel prints a line like
# "https://<random-words>.trycloudflare.com" once the tunnel is up.
_TRYCF_URL_RE = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")
_TUNNEL_URL_TIMEOUT_SEC = 30


class PortProxyMixin:
    """Mixin for managing socat sidecar proxy containers.

    Expects the host class to expose:
      - ``sandbox_id`` (uuid.UUID or None)
      - ``_client`` (docker client)
      - ``_container`` (docker Container or None)
      - ``_container_labels()`` -> dict[str, str]
      - ``_docker_network()`` -> str | None
      - ``_ensure_container_connected()``
      - ``_container_is_running(container)`` (static/classmethod)
    """

    # ------------------------------------------------------------------
    # naming
    # ------------------------------------------------------------------

    def _proxy_network_name(self) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for proxy network")
        return f"giga-sandbox-net-{self.sandbox_id}"

    def _proxy_sandbox_alias(self) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for proxy alias")
        return f"giga-sandbox-{self.sandbox_id}"

    # ------------------------------------------------------------------
    # labels / filters
    # ------------------------------------------------------------------

    def _proxy_container_name(self, port: int, kind: str = PROXY_KIND_SOCAT) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for proxy container")
        if kind == PROXY_KIND_TUNNEL:
            return f"giga-tunnel-{self.sandbox_id}-{port}"
        return f"giga-proxy-{self.sandbox_id}-{port}"

    def _proxy_container_labels(
        self, port: int, kind: str = PROXY_KIND_SOCAT
    ) -> dict[str, str]:
        labels = self._container_labels()
        labels[PROXY_LABEL] = "true"
        labels[PROXY_PORT_LABEL] = str(port)
        labels[PROXY_KIND_LABEL] = kind
        return labels

    @classmethod
    def _proxy_container_filters(cls, sandbox_id: uuid.UUID) -> dict[str, list[str]]:
        return {
            "label": [
                f"{MANAGED_LABEL}=true",
                f"{PROXY_LABEL}=true",
                f"{SANDBOX_ID_LABEL}={sandbox_id}",
            ]
        }

    # ------------------------------------------------------------------
    # discovery (Docker API as source of truth)
    # ------------------------------------------------------------------

    def _find_proxy_containers(self) -> list[Any]:
        if self.sandbox_id is None:
            return []
        return self._client.containers.list(
            all=True,
            filters=self._proxy_container_filters(self.sandbox_id),
        )

    def _find_proxy_for_port(
        self, port: int, kind: str = PROXY_KIND_SOCAT
    ) -> Any | None:
        for container in self._find_proxy_containers():
            labels = getattr(container, "labels", None) or {}
            if labels.get(PROXY_PORT_LABEL) != str(port):
                continue
            # Older proxies predate the kind label; treat them as socat.
            container_kind = labels.get(PROXY_KIND_LABEL, PROXY_KIND_SOCAT)
            if container_kind == kind:
                return container
        return None

    def _find_or_create_proxy_network(self) -> Any:
        net_name = self._proxy_network_name()
        existing = self._client.networks.list(names=[net_name])
        if existing:
            return existing[0]
        logger.info("Creating proxy network %s", net_name)
        return self._client.networks.create(net_name, driver="bridge")

    def _ensure_sandbox_in_network(self, network: Any) -> None:
        if self._container is None:
            raise RuntimeError("Sandbox container is not available")
        self._container.reload()
        connected_networks = (
            (self._container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        )
        if network.name in connected_networks:
            return
        sandbox_alias = self._proxy_sandbox_alias()
        logger.info(
            "Connecting sandbox container %s to network %s as %s",
            self._container.id[:12],
            network.name,
            sandbox_alias,
        )
        network.connect(self._container, aliases=[sandbox_alias])

    # ------------------------------------------------------------------
    # expose
    # ------------------------------------------------------------------

    async def expose_port(self, port: int) -> str:
        """Expose a sandbox port.

        In docker-network mode with ``GIGA_AGENT_PUBLIC_BASE_DOMAIN`` set,
        returns ``https://{port}-sandbox-{sandbox_id_hex}.{domain}`` (proxied
        by the frontend nginx). When there is no nginx mode and
        ``GIGA_AGENT_PUBLISH_CLOUDFLARE_TUNNEL`` is set, spawns a
        ``cloudflared`` quick-tunnel sidecar and returns its public
        ``https://*.trycloudflare.com`` URL. Otherwise spawns a socat sidecar
        and returns ``http://localhost:{host_port}``.
        """
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required to expose a port")
        settings = get_settings()
        docker_network = self._docker_network()
        base_domain = settings.giga_agent_public_base_domain

        if docker_network is not None and base_domain:
            await self._ensure_container_connected()
            self._ensure_hex_alias(docker_network)
            sandbox_hex = self.sandbox_id.hex
            # Clean, token-less URL: the owner opens it via their session cookie
            # (see verify_sandbox_access). A capability token is spliced in only
            # when the URL leaves for a cookie-less surface (e.g. Telegram).
            return f"https://{port}-sandbox-{sandbox_hex}.{base_domain}/"

        if settings.giga_agent_publish_cloudflare_tunnel:
            return await self._expose_via_cloudflare_tunnel(port)

        if docker_network is not None:
            raise RuntimeError(
                "open_port is not available when GIGA_AGENT_DOCKER_NETWORK "
                "is set without GIGA_AGENT_PUBLIC_BASE_DOMAIN "
                "(set GIGA_AGENT_PUBLISH_CLOUDFLARE_TUNNEL=true to use a "
                "Cloudflare quick tunnel instead)"
            )
        await self._ensure_container_connected()

        existing = self._find_proxy_for_port(port)
        if existing is not None:
            try:
                existing.reload()
            except NotFound:
                existing = None

        if existing is not None and self._container_is_running(existing):
            host_port = self._read_host_port(existing, port)
            if host_port is not None:
                return f"http://localhost:{host_port}"

        if existing is not None:
            try:
                existing.remove(force=True)
            except NotFound:
                pass

        network = self._find_or_create_proxy_network()
        self._ensure_sandbox_in_network(network)

        sandbox_alias = self._proxy_sandbox_alias()
        container_name = self._proxy_container_name(port)

        try:
            stale = self._client.containers.get(container_name)
            stale.remove(force=True)
        except NotFound:
            pass

        logger.info(
            "Starting socat proxy %s -> %s:%d",
            container_name,
            sandbox_alias,
            port,
        )
        proxy = self._client.containers.run(
            SOCAT_IMAGE,
            command=f"TCP-LISTEN:{port},fork,reuseaddr TCP:{sandbox_alias}:{port}",
            name=container_name,
            network=network.name,
            ports={f"{port}/tcp": None},
            labels=self._proxy_container_labels(port),
            detach=True,
            remove=True,
        )
        proxy.reload()

        host_port = self._read_host_port(proxy, port)
        if host_port is None:
            raise RuntimeError(
                f"Could not determine host port for proxy container {container_name}"
            )
        return f"http://localhost:{host_port}"

    # ------------------------------------------------------------------
    # cloudflare quick tunnel
    # ------------------------------------------------------------------

    async def _expose_via_cloudflare_tunnel(self, port: int) -> str:
        """Expose *port* through a ``cloudflared`` quick-tunnel sidecar.

        The sidecar joins the sandbox proxy network and reaches the app at
        ``http://{sandbox_alias}:{port}`` via Docker DNS; no host port is
        published since cloudflared connects outbound to Cloudflare's edge.
        The assigned ``*.trycloudflare.com`` URL is read back from the
        sidecar's logs. Reuses a running sidecar for the same port.
        """
        await self._ensure_container_connected()

        existing = self._find_proxy_for_port(port, kind=PROXY_KIND_TUNNEL)
        if existing is not None:
            try:
                existing.reload()
            except NotFound:
                existing = None

        if existing is not None and self._container_is_running(existing):
            url = await self._wait_for_tunnel_url(existing)
            if url is not None:
                return url

        if existing is not None:
            try:
                existing.remove(force=True)
            except NotFound:
                pass

        network = self._find_or_create_proxy_network()
        self._ensure_sandbox_in_network(network)

        sandbox_alias = self._proxy_sandbox_alias()
        container_name = self._proxy_container_name(port, kind=PROXY_KIND_TUNNEL)

        try:
            stale = self._client.containers.get(container_name)
            stale.remove(force=True)
        except NotFound:
            pass

        logger.info(
            "Starting cloudflared quick tunnel %s -> %s:%d",
            container_name,
            sandbox_alias,
            port,
        )
        # The cloudflare/cloudflared image ENTRYPOINT is
        # ["cloudflared", "--no-autoupdate"], so the command is just the
        # subcommand + its flags.
        tunnel = self._client.containers.run(
            CLOUDFLARED_IMAGE,
            command=f"tunnel --url http://{sandbox_alias}:{port}",
            name=container_name,
            network=network.name,
            labels=self._proxy_container_labels(port, kind=PROXY_KIND_TUNNEL),
            detach=True,
            remove=True,
        )

        url = await self._wait_for_tunnel_url(tunnel)
        if url is None:
            try:
                tunnel.remove(force=True)
            except NotFound:
                pass
            raise RuntimeError(
                "cloudflared did not report a tunnel URL within "
                f"{_TUNNEL_URL_TIMEOUT_SEC}s for port {port}"
            )
        return url

    async def _wait_for_tunnel_url(self, container: Any) -> str | None:
        """Poll *container* logs for the assigned ``trycloudflare.com`` URL."""
        deadline = time.monotonic() + _TUNNEL_URL_TIMEOUT_SEC
        while time.monotonic() < deadline:
            try:
                container.reload()
            except NotFound:
                return None
            try:
                logs = container.logs(stdout=True, stderr=True)
            except DockerException:
                logs = b""
            match = _TRYCF_URL_RE.search(logs)
            if match is not None:
                return match.group(0).decode()
            # If cloudflared exited before emitting a URL, stop waiting.
            if not self._container_is_running(container):
                return None
            await asyncio.sleep(0.5)
        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _disconnect_all_from_network(network: Any) -> None:
        """Disconnect every container from *network* so it can be removed."""
        try:
            network.reload()
        except Exception:
            return
        for cid in list((network.attrs.get("Containers") or {}).keys()):
            try:
                network.disconnect(cid, force=True)
            except Exception:
                pass

    @staticmethod
    def _read_host_port(container: Any, port: int) -> int | None:
        ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
        binding = ports.get(f"{port}/tcp")
        if binding:
            return int(binding[0]["HostPort"])
        return None

    # ------------------------------------------------------------------
    # instance-level cleanup
    # ------------------------------------------------------------------

    def _stop_proxy_containers(self) -> None:
        """Stop and remove all proxy sidecar containers for this sandbox."""
        for container in self._find_proxy_containers():
            cid = getattr(container, "id", "")
            try:
                container.remove(force=True)
                logger.info("Removed proxy container %s", cid[:12])
            except NotFound:
                pass
            except Exception:
                logger.warning(
                    "Failed to remove proxy container %s", cid[:12], exc_info=True,
                )

    def _remove_proxy_network(self) -> None:
        """Remove the temporary proxy network for this sandbox."""
        if self.sandbox_id is None:
            return
        net_name = self._proxy_network_name()
        try:
            existing = self._client.networks.list(names=[net_name])
            for net in existing:
                if net.name == net_name:
                    self._disconnect_all_from_network(net)
                    net.remove()
                    logger.info("Removed proxy network %s", net_name)
        except Exception:
            logger.warning(
                "Failed to remove proxy network %s", net_name, exc_info=True,
            )

    # ------------------------------------------------------------------
    # class-level cleanup (for orphan GC and external runtime ops)
    # ------------------------------------------------------------------

    @classmethod
    def _cleanup_proxy_for_sandbox(
        cls,
        client: Any,
        sandbox_id: uuid.UUID,
    ) -> None:
        """Remove all proxy containers and network for a given sandbox."""
        try:
            containers = client.containers.list(
                all=True,
                filters=cls._proxy_container_filters(sandbox_id),
            )
            for container in containers:
                cid = getattr(container, "id", "")
                try:
                    container.remove(force=True)
                except NotFound:
                    pass
                except Exception:
                    logger.warning(
                        "Failed to remove orphan proxy container %s", cid[:12],
                        exc_info=True,
                    )
        except DockerException:
            pass

        net_name = f"giga-sandbox-net-{sandbox_id}"
        try:
            networks = client.networks.list(names=[net_name])
            for net in networks:
                if net.name == net_name:
                    cls._disconnect_all_from_network(net)
                    net.remove()
        except Exception:
            pass
