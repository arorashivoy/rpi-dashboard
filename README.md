# Pi Control Room

A small Raspberry Pi service dashboard built with Python's standard library and static browser files. It can start and stop configured command applications, systemd units, and existing Docker containers. It has no Python package dependencies and does not poll in the background.

## Configure applications

Copy the example configuration and edit it for the Pi:

```sh
cp apps.example.json apps.json
chmod 600 apps.json
```

Set each app's `kind`, `start` command or systemd unit/container, working directory, port, and local URL. Commands are argument arrays rather than shell strings. Empty `start` arrays disable a command app until configured. Use `managed: false` for read-only entries such as the dashboard itself.

The dashboard entry should use `kind: "systemd"`, `scope: "user"`, and `unit: "rpi-dashboard.service"`. This lets the dashboard report its own status without offering a button that could stop itself.

## Cloudflare hostnames

Set a base domain and a route on each app:

```json
{
  "cloudflare": { "domain": "arorashivoy.win" },
  "apps": [
    {
      "id": "rpi-dashboard",
      "name": "Raspberry Pi Dashboard",
      "kind": "systemd",
      "scope": "user",
      "unit": "rpi-dashboard.service",
      "port": 8787,
      "url": "http://127.0.0.1:8787",
      "managed": false,
      "cloudflare": { "subdomain": "dashboard", "visibility": "private" }
    }
  ]
}
```

`cloudflare.subdomain` selects the hostname. `cloudflare.visibility` is `private` or `public` and defaults to `private`. A private hostname must also have a Cloudflare Access application and Allow policy. For email PIN access, use an exact email allowlist. Public hostnames have no Access gate.

These fields describe the expected address and visibility in the dashboard. They do not create DNS records or Access policies. Configure each published application route in the Cloudflare Tunnel, and create its Access application before publishing a private hostname. The Tunnel should send only to the app's local address and port.

The Raspberry Pi Tunnel runs as one systemd user service using the configuration and tunnel credentials under `~/.cloudflared/`. Protect the credentials file and keep it out of Git. Install the service template with:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rpi-dashboard-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard-tunnel.service
```

The unit expects `~/.cloudflared/rpi-dashboard.yml` to contain the named tunnel UUID, credentials file path, hostname ingress routes, and a final `http_status:404` catch-all. After changing that file, restart the Tunnel:

```sh
systemctl --user restart rpi-dashboard-tunnel.service
systemctl --user status rpi-dashboard-tunnel.service
```

## Run the dashboard

```sh
python3 server.py
```

Open `http://127.0.0.1:8787`. The dashboard binds to loopback by default and has no built-in login. Keep it behind Cloudflare Access or use an SSH tunnel; do not expose the local port directly.

## Start at boot

Install the included dashboard user service:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rpi-dashboard.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard.service
```

The dashboard starts configured apps whose `autostart` value is true. It skips disabled apps. For Docker control, the dashboard user needs Docker access; Docker group membership grants broad control over the host.

For a group of existing user services, configure one app with `kind: "systemd"`, `scope: "user"`, and a `units` array. The group is reported as running only when every unit is active.

## Configuration reference

- `id`: unique letters, numbers, `_`, or `-`.
- `kind`: `command` (default), `systemd`, or `docker`.
- `scope`: `system` (default) or `user` for systemd-managed apps.
- `unit` or `units`: one systemd unit name or a list of units.
- `managed`: set to `false` for status-only entries.
- `autostart`: start this app when the dashboard service starts.
- `start`: executable and arguments for command apps.
- `stop.signal`: process signal for command apps; defaults to `SIGINT`.
- `stop.command`: optional executable and arguments that replace signal-based stopping.
- `port` and `url`: local endpoint shown in the dashboard.
- top-level `cloudflare.domain`: base domain used to display app hostnames.
- `cloudflare.subdomain`: DNS label for this app, such as `dashboard`.
- `cloudflare.visibility`: `private` (default) or `public`.

The browser fetches status when a tab opens and when you click Refresh. It does not poll in the background. Service actions update the current tab using the action response. Valid configuration changes appear after clicking Refresh; if the JSON is invalid, the dashboard keeps the last valid configuration and shows an error.
