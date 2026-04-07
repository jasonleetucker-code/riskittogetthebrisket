"""Tests for Next.js frontend migration: runtime default, login, deploy config."""

from __future__ import annotations

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestFrontendRuntimeDefault(unittest.TestCase):
    """FRONTEND_RUNTIME must default to 'next', not 'static'."""

    def test_server_py_defaults_to_next(self):
        """The fallback FRONTEND_RUNTIME in server.py must be 'next'."""
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        # The line that sets the default when the env var is unset/invalid
        self.assertIn('FRONTEND_RUNTIME = "next"', text)
        # Must NOT default to static
        self.assertNotIn('FRONTEND_RUNTIME = "static"', text)

    def test_env_example_shows_next_as_default(self):
        env_example = REPO_ROOT / ".env.example"
        text = env_example.read_text()
        self.assertIn("FRONTEND_RUNTIME=next", text)


class TestLoginPageUsesServerAuth(unittest.TestCase):
    """Next.js login page must POST to /api/auth/login, not use localStorage."""

    def test_login_page_calls_api_auth_login(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        self.assertIn("/api/auth/login", text)

    def test_login_page_does_not_use_localstorage(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        self.assertNotIn("localStorage", text)

    def test_login_page_sends_username_not_email(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        # The form must send a username field, not email
        self.assertIn("username", text)
        # Should not have an email input type for the primary credential
        self.assertNotIn('type="email"', text)

    def test_login_page_handles_error_response(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        # Must handle non-ok responses (401)
        self.assertIn("data.error", text)


class TestDeployConfig(unittest.TestCase):
    """Production deployment must include both backend and frontend services."""

    def test_frontend_service_template_exists(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty-frontend.service.template"
        self.assertTrue(template.exists(), "Frontend systemd service template must exist")

    def test_frontend_service_runs_npm_start(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty-frontend.service.template"
        text = template.read_text()
        self.assertIn("npm start", text)
        self.assertIn("PORT=3000", text)

    def test_backend_service_depends_on_frontend(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty.service.template"
        text = template.read_text()
        self.assertIn("frontend.service", text)

    def test_deploy_builds_frontend_by_default(self):
        deploy_sh = REPO_ROOT / "deploy" / "deploy.sh"
        text = deploy_sh.read_text()
        self.assertIn('RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-true}"', text)

    def test_install_script_handles_frontend_service(self):
        install_sh = REPO_ROOT / "deploy" / "install-systemd-service.sh"
        text = install_sh.read_text()
        self.assertIn("dynasty-frontend.service.template", text)
