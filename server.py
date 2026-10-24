#!/usr/bin/env python3
"""Small local dashboard for Raspberry Pi services."""

import json
import os
import re
import signal
import subprocess
import threading
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("RPI_DASHBOARD_CONFIG", ROOT / "apps.json"))
URL_PATTERN = re.compile(r"https?://[^\s\]\[()\"']+")


def config_file_path():
    return CONFIG_PATH if CONFIG_PATH.exists() else ROOT / "apps.example.json"


class Dashboard:
    def __init__(self, config, config_path=None):
        self.config = config
        self.apps = {app["id"]: app for app in config.get("apps", [])}
        self.config_path = config_path or config_file_path()
        self.config_mtime_ns = self.config_path.stat().st_mtime_ns
        self.processes = {}
        self.share_processes = {}
        self.share_urls = {}
        self.errors = {}
        self.lock = threading.RLock()

    def app_status(self, app):
        app_id = app["id"]
        kind = app.get("kind", "command")
        with self.lock:
            process = self.processes.get(app_id)
            share_process = self.share_processes.get(app_id)
            running_process = process is not None and process.poll() is None
            sharing = share_process is not None and share_process.poll() is None
            share_url = self.share_urls.get(app_id)
            error = self.errors.get(app_id)

        if kind == "systemd":
            running = all(
                self._check_command(self._systemctl_command(app, "is-active", "--quiet", unit=unit))
                for unit in self._systemd_units(app)
            )
        elif kind == "docker":
            running = self._check_command(
                ["docker", "inspect", "--format", "{{.State.Running}}", app["container"]],
                expected_output="true",
            )
        else:
            running = running_process

        port = app.get("port")
        local_url = app.get("url") or (f"http://127.0.0.1:{port}" if port else None)
        if local_url and port:
            local_url = local_url.replace("${port}", str(port))

        return {
            "id": app_id,
            "name": app.get("name", app_id),
            "description": app.get("description", ""),
            "kind": kind,
            "port": port,
            "local_url": local_url,
            "running": bool(running),
            "sharing": sharing,
            "share_url": share_url,
            "share_mode": app.get("share", {}).get("mode") if app.get("share") else None,
            "disabled": bool(app.get("disabled") or (kind == "command" and not app.get("start"))),
            "error": error,
        }

    def list_apps(self):
        return [self.app_status(app) for app in self.config.get("apps", [])]

    def reload_config(self):
        try:
            modified_ns = self.config_path.stat().st_mtime_ns
            if modified_ns == self.config_mtime_ns:
                return False
            config = load_config(self.config_path)
            modified_ns = self.config_path.stat().st_mtime_ns
        except (OSError, ValueError) as exc:
            raise ValueError(f"Could not reload {self.config_path.name}: {exc}") from exc

        with self.lock:
            self.config = config
            self.apps = {app["id"]: app for app in config.get("apps", [])}
            self.config_mtime_ns = modified_ns
        return True

    def start_app(self, app_id):
        app = self._get_app(app_id)
        kind = app.get("kind", "command")
        if app.get("disabled") or (kind == "command" and not app.get("start")):
            raise ValueError("Configure a start command before launching this application")
        try:
            if kind == "systemd":
                self._run_checked(self._systemctl_command(app, "start"))
            elif kind == "docker":
                self._run_checked(["docker", "start", app["container"]])
            elif kind == "command":
                with self.lock:
                    existing = self.processes.get(app_id)
                    if existing and existing.poll() is None:
                        return self.app_status(app)
                    self.processes[app_id] = subprocess.Popen(
                        app["start"],
                        cwd=app.get("working_dir") or None,
                        env={**os.environ, **app.get("environment", {})},
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
            else:
                raise ValueError(f"Unsupported service kind: {kind}")
            with self.lock:
                self.errors.pop(app_id, None)
            return self.app_status(app)
        except FileNotFoundError as exc:
            start = app.get("start")
            if start and isinstance(start[0], str) and any(char.isspace() for char in start[0]):
                message = (
                    f"Executable {start[0]!r} was not found. Put the executable and its arguments "
                    'in separate start entries, for example ["npm", "start"].'
                )
            else:
                message = str(exc)
            self._set_error(app_id, message)
            raise RuntimeError(message) from exc
        except (KeyError, OSError, subprocess.SubprocessError) as exc:
            self._set_error(app_id, exc)
            raise RuntimeError(str(exc)) from exc

    def stop_app(self, app_id):
        app = self._get_app(app_id)
        kind = app.get("kind", "command")
        try:
            if kind == "systemd":
                self._run_checked(self._systemctl_command(app, "stop"))
            elif kind == "docker":
                self._run_checked(["docker", "stop", app["container"]])
            else:
                with self.lock:
                    process = self.processes.get(app_id)
                if process and process.poll() is None:
                    stop = app.get("stop", {})
                    if stop.get("command"):
                        self._run_checked(stop["command"], cwd=app.get("working_dir") or None)
                    else:
                        stop_signal = getattr(signal, stop.get("signal", "SIGINT"), signal.SIGINT)
                        os.killpg(process.pid, stop_signal)
                        try:
                            process.wait(timeout=float(stop.get("timeout_seconds", 8)))
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait(timeout=3)
            with self.lock:
                self.errors.pop(app_id, None)
            return self.app_status(app)
        except (KeyError, OSError, subprocess.SubprocessError) as exc:
            self._set_error(app_id, exc)
            raise RuntimeError(str(exc)) from exc

    def start_share(self, app_id):
        app = self._get_app(app_id)
        share = app.get("share")
        if not share:
            raise ValueError("Sharing is not configured for this application")
        with self.lock:
            existing = self.share_processes.get(app_id)
            if existing and existing.poll() is None:
                return self.app_status(app)

        mode = share.get("mode", "random")
        target = share.get("target") or (f"localhost:{app['port']}" if app.get("port") else None)
        if mode in {"random", "named"}:
            if not target:
                raise ValueError("Set a port or share.target before starting a share")
            command = share.get("command") or ["zrok2", "share", "public", "--headless", target]
            if mode == "named":
                name = share.get("name", "")
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                    raise ValueError("Set share.name to a valid zrok name")
                command = [*command, "--name-selection", f"public:{name}"]
        elif mode == "reserved":
            token = share.get("token")
            if not token:
                raise ValueError("Set share.token to the reserved zrok token")
            command = share.get("command") or ["zrok2", "share", "reserved", "--headless", token]
        else:
            raise ValueError("share.mode must be 'random', 'named', or 'reserved'")
        basic_auth = share.get("basic_auth")
        if basic_auth:
            username = basic_auth.get("username", "")
            password = basic_auth.get("password", "")
            if not username or not password or ":" in username or ":" in password:
                raise ValueError("share.basic_auth needs a username and password without ':'")
            command = [*command, f"--basic-auth={username}:{password}"]

        try:
            process = subprocess.Popen(
                command,
                cwd=app.get("working_dir") or None,
                env={**os.environ, **app.get("environment", {})},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with self.lock:
                self.share_processes[app_id] = process
                self.share_urls.pop(app_id, None)
                self.errors.pop(app_id, None)
            threading.Thread(target=self._read_share_output, args=(app_id, process), daemon=True).start()
            return self.app_status(app)
        except (KeyError, OSError, subprocess.SubprocessError, ValueError) as exc:
            self._set_error(app_id, exc)
            raise RuntimeError(str(exc)) from exc

    def stop_share(self, app_id):
        app = self._get_app(app_id)
        with self.lock:
            process = self.share_processes.get(app_id)
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
            except OSError as exc:
                self._set_error(app_id, exc)
                raise RuntimeError(str(exc)) from exc
        with self.lock:
            self.share_urls.pop(app_id, None)
            self.errors.pop(app_id, None)
        return self.app_status(app)

    def _read_share_output(self, app_id, process):
        lines = deque(maxlen=80)
        if process.stdout is None:
            return
        for line in process.stdout:
            lines.append(line.rstrip())
            matches = URL_PATTERN.findall(line)
            if matches:
                with self.lock:
                    self.share_urls[app_id] = matches[-1].rstrip(".,;:")
        return_code = process.wait()
        with self.lock:
            if return_code and self.share_processes.get(app_id) is process:
                message = "\n".join(lines).strip() or f"zrok2 exited with status {return_code}"
                self.errors[app_id] = message[-1200:]
                self.share_urls.pop(app_id, None)

    def _get_app(self, app_id):
        try:
            return self.apps[app_id]
        except KeyError as exc:
            raise ValueError("Application not found") from exc

    def _set_error(self, app_id, error):
        with self.lock:
            self.errors[app_id] = str(error)

    @staticmethod
    def _run_checked(command, cwd=None):
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or f"Command failed with status {result.returncode}")

    @staticmethod
    def _check_command(command, expected_output=None):
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE if expected_output is not None else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            if result.returncode:
                return False
            return expected_output is None or result.stdout.strip().lower() == expected_output
        except OSError:
            return False

    @staticmethod
    def _systemctl_command(app, *arguments, unit=None):
        command = ["systemctl"]
        if app.get("scope", "system") == "user":
            command.append("--user")
        units = [unit] if unit else Dashboard._systemd_units(app)
        return [*command, *arguments, *units]

    @staticmethod
    def _systemd_units(app):
        return app.get("units") or [app["unit"]]


def load_config(path=None):
    path = path or config_file_path()
    with path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    seen = set()
    for app in config.get("apps", []):
        app_id = app.get("id", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", app_id) or app_id in seen:
            raise ValueError(f"Invalid or duplicate application id: {app_id!r}")
        seen.add(app_id)
        kind = app.get("kind", "command")
        if kind == "command" and not app.get("start"):
            app["disabled"] = True
        elif kind == "systemd":
            units = app.get("units")
            if units is not None:
                if not isinstance(units, list) or not units or any(not isinstance(unit, str) or not unit for unit in units):
                    raise ValueError(f"Application {app_id!r} needs a non-empty list of systemd units")
                if app.get("unit"):
                    raise ValueError(f"Application {app_id!r} cannot set both 'unit' and 'units'")
            elif not app.get("unit"):
                raise ValueError(f"Application {app_id!r} needs a systemd unit or units list")
            if app.get("scope", "system") not in {"system", "user"}:
                raise ValueError(f"Application {app_id!r} systemd scope must be 'system' or 'user'")
        elif kind == "docker" and not app.get("container"):
            raise ValueError(f"Application {app_id!r} needs a Docker container")
        elif kind not in {"command", "systemd", "docker"}:
            raise ValueError(f"Application {app_id!r} has unsupported kind: {kind}")
    return config


class Handler(SimpleHTTPRequestHandler):
    dashboard = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def do_GET(self):
        if self.path == "/api/apps":
            self._json(200, {"apps": self.dashboard.list_apps()})
        elif self.path == "/api/health":
            self._json(200, {"ok": True})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/reload":
            try:
                reloaded = self.dashboard.reload_config()
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"apps": self.dashboard.list_apps(), "reloaded": reloaded})
            return

        match = re.fullmatch(r"/api/apps/([^/]+)/(start|stop|share|unshare)", urlparse(self.path).path)
        if not match:
            self._json(404, {"error": "Not found"})
            return
        app_id, action = unquote(match.group(1)), match.group(2)
        try:
            result = {
                "start": self.dashboard.start_app,
                "stop": self.dashboard.stop_app,
                "share": self.dashboard.start_share,
                "unshare": self.dashboard.stop_share,
            }[action](app_id)
            self._json(200, {"app": result})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(500, {"error": str(exc)})

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"[{self.log_date_time_string()}] {format_string % args}")


def main():
    config = load_config()
    dashboard = Dashboard(config)
    Handler.dashboard = dashboard

    for app in config.get("apps", []):
        startup_failed = False
        if app.get("autostart") and not app.get("disabled"):
            try:
                dashboard.start_app(app["id"])
            except (RuntimeError, ValueError) as exc:
                startup_failed = True
                print(f"Could not start {app['id']}: {exc}")
        if app.get("share", {}).get("autostart") and not app.get("disabled") and not startup_failed:
            try:
                dashboard.start_share(app["id"])
            except (RuntimeError, ValueError) as exc:
                print(f"Could not start {app['id']} share: {exc}")

    host = os.environ.get("RPI_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("RPI_DASHBOARD_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Raspberry Pi dashboard listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()