import types
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.local_functions import (
    DirectoryPickerFailedError,
    DirectoryPickerUnavailableError,
    pick_directory,
    router,
)


class LocalFunctionsRouterTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)

        async def _override_current_user():
            return self.user

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.client = TestClient(self.app)

    def test_directory_picker_returns_selected_path(self):
        with patch(
            "giga_agent.routes.local_functions.pick_directory",
            return_value="/tmp/work",
        ):
            response = self.client.post("/local-functions/directory-picker")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"path": "/tmp/work"})

    def test_directory_picker_returns_null_on_cancel(self):
        with patch("giga_agent.routes.local_functions.pick_directory", return_value=None):
            response = self.client.post("/local-functions/directory-picker")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"path": None})

    def test_directory_picker_reports_unavailable_picker(self):
        with patch(
            "giga_agent.routes.local_functions.pick_directory",
            side_effect=DirectoryPickerUnavailableError("zenity or kdialog is required"),
        ):
            response = self.client.post("/local-functions/directory-picker")

        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["detail"], "zenity or kdialog is required")

    def test_directory_picker_reports_failed_picker(self):
        with patch(
            "giga_agent.routes.local_functions.pick_directory",
            side_effect=DirectoryPickerFailedError("Picker failed"),
        ):
            response = self.client.post("/local-functions/directory-picker")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Picker failed")

    def test_macos_picker_uses_osascript(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout="/tmp/selected/\n",
            stderr="",
        )

        with (
            patch("giga_agent.routes.local_functions.platform.system", return_value="Darwin"),
            patch("giga_agent.routes.local_functions.shutil.which", return_value="osascript"),
            patch("giga_agent.routes.local_functions.subprocess.run", return_value=completed) as run,
        ):
            selected_path = pick_directory()

        self.assertEqual(selected_path, "/tmp/selected")
        self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_linux_picker_uses_zenity_when_available(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout="/tmp/selected\n",
            stderr="",
        )

        with (
            patch("giga_agent.routes.local_functions.platform.system", return_value="Linux"),
            patch("giga_agent.routes.local_functions.shutil.which", return_value="zenity"),
            patch("giga_agent.routes.local_functions.subprocess.run", return_value=completed) as run,
        ):
            selected_path = pick_directory()

        self.assertEqual(selected_path, "/tmp/selected")
        self.assertIn("--file-selection", run.call_args.args[0])
