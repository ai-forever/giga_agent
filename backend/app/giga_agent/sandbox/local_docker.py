import secrets
import time
import os
import asyncio
import logging
import docker
from typing import Optional, Any

from dotenv import load_dotenv
from pydantic import Field, PrivateAttr
from giga_agent.sandbox.jupyter import JupyterSandbox

logger = logging.getLogger(__name__)

load_dotenv()


class LocalDockerSandbox(JupyterSandbox):
    image: str = Field(
        default="mikelarg/code-interpreter:0.0.4", description="Docker image to use"
    )

    _client: Any = PrivateAttr(default=None)
    _container: Any = PrivateAttr(default=None)

    def __init__(self, **data):
        super().__init__(base_url="", **data)
        self._client = docker.from_env()

    async def up(self) -> None:
        """Запускает Docker контейнер и настраивает окружение."""
        # Generate tokens and load envs
        self._token = secrets.token_urlsafe(13)
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        if not aws_access_key or not aws_secret_key:
            logger.warning(
                "⚠️  Warning: AWS credentials not found in environment variables"
            )

        logger.info("🚀 Starting Docker container...")

        # 1. Start Docker container with sleep infinity
        self._container = self._client.containers.run(
            self.image,
            command="sleep infinity",
            detach=True,
            remove=True,  # Automatically remove container when it stops
            privileged=True,  # Needed for s3fs fuse mounting
            environment={
                "JUPYTER_TOKEN": self._token,
                "AWSACCESSKEYID": aws_access_key,
                "AWSSECRETACCESSKEY": aws_secret_key,
                "MATPLOTLIBRC": "/root/.config/matplotlib/.matplotlibrc",
            },
            ports={"8888/tcp": None},  # Map 8888 to a random host port
        )

        logger.info(f"📦 Container started with ID: {self._container.id[:12]}")

        # 2. Run setup commands inside container
        logger.info("⚙️  Configuring environment...")

        # Create directory
        self._container.exec_run("mkdir -p /home/user/bucket/")

        # Mount S3
        logger.info("☁️  Mounting S3...")
        s3_cmd = (
            "s3fs giga-agent /home/user/bucket "
            "-o url=https://s3.cloud.ru "
            "-o endpoint=ru-central-1 "
            "-o use_path_request_style "
            "-o allow_other"
        )
        # Using sh -c to ensure complex command string works
        exit_code, output = self._container.exec_run(f"sh -c '{s3_cmd}'")
        if exit_code != 0:
            logger.warning(f"Warning: S3 mount failed: {output.decode()}")

        # 3. Start Jupyter Server
        logger.info("📓 Starting Jupyter Server...")
        # Start in background
        jupyter_cmd = (
            f"jupyter server --ip=0.0.0.0 --port=8888 --allow-root > /dev/null 2>&1 &"
        )
        self._container.exec_run(f"sh -c '{jupyter_cmd}'", detach=True)

        # 4. Get connection details
        # Reload container attributes to get assigned ports
        self._container.reload()
        ports = self._container.attrs["NetworkSettings"]["Ports"]
        if "8888/tcp" in ports and ports["8888/tcp"]:
            host_port = ports["8888/tcp"][0]["HostPort"]
        else:
            raise RuntimeError("Could not find mapped port for 8888")

        self.base_url = f"http://localhost:{host_port}"
        logger.info(f"🔗 Jupyter available at: {self.base_url}")
        logger.info(f"🔑 Token: {self._token}")

        # Wait for Jupyter to be ready
        TIMEOUT_SECONDS = 15
        start_time = time.time()

        while True:
            if await self.is_up():
                logger.info("✅ Jupyter is up and connected")
                break

            if time.time() - start_time > TIMEOUT_SECONDS:
                raise TimeoutError(
                    f"Jupyter did not start within {TIMEOUT_SECONDS} seconds"
                )
            logger.debug("⏳ Waiting for Jupyter...")
            await asyncio.sleep(1)

    def stop(self):
        if self._container:
            logger.info(f"🧹 Cleaning up container {self._container.id[:12]}...")
            self._container.stop()
            self._container = None


async def main():
    sandbox = LocalDockerSandbox()
    try:
        await sandbox.up()

        # 6. Run Tests
        code = """
print('Hello from Jupyter')
name = input()
print(f'Hello {name}')

import os
try:
    print(f"Bucket content: {os.listdir('/home/user/bucket')}")
    with open('/home/user/bucket/docker_test.txt', 'w') as f:
        f.write('Hello from Docker Jupyter')
    print("Successfully wrote to bucket")
except Exception as e:
    print(f"Error accessing bucket: {e}")
"""
        logger.info("🧪 Running test code...")
        gen = sandbox.run_code(code)

        try:
            # Note: In async generator, we use anext or async for
            output = await anext(gen)

            while True:
                logger.info(f"Received: {output}")
                if output["type"] == "input_request":
                    logger.info(f"Providing input for prompt: {output.get('prompt')}")
                    output = await gen.asend("GigaUser")
                else:
                    output = await anext(gen)
        except StopAsyncIteration:
            pass

        logger.info("✨ Test completed successfully")

    except Exception as e:
        logger.error(f"❌ An error occurred: {e}", exc_info=True)
    finally:
        sandbox.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
