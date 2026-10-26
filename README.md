# Pi Control Room

A lightweight Raspberry Pi dashboard built with Python's standard library and static browser files. It starts and stops configured command applications, systemd units, and existing Docker containers. Cloudflare Tunnel publishes selected web apps; this project has no zrok dependency. The browser refreshes status when a tab opens or when you press Refresh; it does not poll in the background.

## Applications

Copy the example configuration and edit it for the Pi:

```sh
cp apps.example.json apps.json
chmod 600 apps.json
```

Each app needs a unique `id`, a `kind`, and any fields required for that kind:

- `command`: `start` is an argument array, not a shell command string. Set `working_dir` and `port` for web apps. An empty `start` array disables the app.
- `systemd`: set `unit` or `units`. Use `scope: "user"` for a user service.
- `docker`: set `container` to an existing container name.

Set `autostart` to `true` only for apps that should start with the dashboard. The dashboard itself belongs in `apps.json` as a status-only entry (`managed: false`) so it cannot stop itself.

The current hostname and origin mapping is:

| App | Public hostname | Pi origin | Access |
| --- | --- | --- | --- |
| Dashboard | `dashboard.arorashivoy.win` | `127.0.0.1:8787` | Private; email allowlist |
| Block Logic Puzzle | `block-logic.arorashivoy.win` | `127.0.0.1:4173` | Private; email allowlist |
| Two Rooms and a Boom | `two-rooms.arorashivoy.win` | `127.0.0.1:5001` | Public |
| Waypoint | `waypoint.arorashivoy.win` | `localhost:3118` | Private; separate Tunnel service |

Pi-hole stays local and is not published through Cloudflare.

Two Rooms is configured not to autostart. Launch it from the dashboard when you plan to play; its public hostname will return an origin error while the game is stopped.

## Cloudflare Tunnel and Access

The dashboard Tunnel carries the dashboard, Block Logic, and Two Rooms hostnames through one `cloudflared` process. Waypoint has its own existing Tunnel service. Tunnel credentials and configuration stay under `~/.cloudflared/`; do not put credentials in Git or `apps.json`.

For a new locally-managed Tunnel:

1. Make sure `arorashivoy.win` is active in Cloudflare DNS and install `cloudflared` on the Pi.
2. Authenticate as the Pi user and create the Tunnel:

   ```sh
   cloudflared tunnel login
   cloudflared tunnel create rpi-dashboard
   ```

   If the Pi has no browser, open the login URL printed by `cloudflared tunnel login` on another device and select `arorashivoy.win`. Save the Tunnel UUID printed by the create command. It creates a credentials JSON file under `~/.cloudflared/`.
3. Create `~/.cloudflared/rpi-dashboard.yml` with that UUID and credentials path. Use the current routes as a starting point:

   ```yaml
   tunnel: <TUNNEL_UUID>
   credentials-file: /home/shivoy/.cloudflared/<TUNNEL_UUID>.json
   ingress:
     - hostname: dashboard.arorashivoy.win
       service: http://127.0.0.1:8787
     - hostname: block-logic.arorashivoy.win
       service: http://127.0.0.1:4173
     - hostname: two-rooms.arorashivoy.win
       service: http://127.0.0.1:5001
     - service: http_status:404
   ```

   Replace `<TUNNEL_UUID>` with the ID from step 2, then restrict the files:

   ```sh
   TUNNEL_ID="<TUNNEL_UUID>"
   chmod 600 ~/.cloudflared/rpi-dashboard.yml "$HOME/.cloudflared/${TUNNEL_ID}.json"
   cloudflared --config ~/.cloudflared/rpi-dashboard.yml tunnel ingress validate
   ```

4. In Cloudflare Zero Trust, create Self-hosted Access applications for the private dashboard and Block Logic hostnames. Give each an Allow policy with the intended email addresses; restrict the dashboard to your own address. Two Rooms is public, so do not create an Access application for it. Create Access applications before DNS routes so private apps are not briefly reachable without their gate.
5. Create the DNS routes:

   ```sh
   cloudflared tunnel route dns rpi-dashboard dashboard.arorashivoy.win
   cloudflared tunnel route dns rpi-dashboard block-logic.arorashivoy.win
   cloudflared tunnel route dns rpi-dashboard two-rooms.arorashivoy.win
   ```

6. Install and enable the user service:

   ```sh
   mkdir -p ~/.config/systemd/user
   cp systemd/rpi-dashboard-tunnel.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now rpi-dashboard-tunnel.service
   ```

   Enable lingering if the user service should run after reboot without an interactive login:

   ```sh
   sudo loginctl enable-linger "$USER"
   ```

When you edit the Tunnel YAML, validate it and restart the Tunnel:

```sh
cloudflared --config ~/.cloudflared/rpi-dashboard.yml tunnel ingress validate
systemctl --user restart rpi-dashboard-tunnel.service
systemctl --user status rpi-dashboard-tunnel.service
```

### Private and public hostnames

`cloudflare.subdomain` and `cloudflare.visibility` in `apps.json` control the address and label shown in the dashboard. They do not create DNS routes or Access policies. Configure the matching Tunnel route and Access settings in Cloudflare as well.

- **Private:** create a Cloudflare Zero Trust Access application for that hostname and an Allow policy with the exact email addresses that should get in. Enable email One-Time PIN if users should sign in with a code. Keep the dashboard limited to your own email.
- **Public:** do not attach an Access application to the hostname. Anyone can reach the app while it is running. Two Rooms is public so friends can join without signing in.

For the live setup, the dashboard and Block Logic have explicit email allowlists. Two Rooms has no Access gate. Changing `visibility` in `apps.json` alone does not add or remove that gate.

## Run the dashboard

Run it directly for local use:

```sh
python3 server.py
```

Open `http://127.0.0.1:8787`. The dashboard binds to loopback by default and has no built-in login. Keep it behind Cloudflare Access or use an SSH tunnel; do not expose the local port directly.

## Dashboard systemd service

Install and enable the included user service:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rpi-dashboard.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard.service
systemctl --user status rpi-dashboard.service
```

The dashboard starts apps whose `autostart` value is true and skips disabled apps. For Docker control, the dashboard user needs Docker access; Docker group membership grants broad control over the host.

## Configuration reference

- `id`: unique letters, numbers, `_`, or `-`.
- `kind`: `command` (default), `systemd`, or `docker`.
- `scope`: `system` (default) or `user` for systemd-managed apps.
- `unit` or `units`: one systemd unit name or a list of units.
- `managed`: set to `false` for status-only entries such as the dashboard.
- `autostart`: start this app when the dashboard service starts.
- `start`: executable and arguments for a command app.
- `stop.signal`: process signal for a command app; defaults to `SIGINT`.
- `stop.command`: optional executable and arguments that replace signal-based stopping.
- `port` and `url`: local endpoint shown in the dashboard.
- top-level `cloudflare.domain`: domain appended to app subdomains.
- `cloudflare.subdomain`: hostname label, such as `dashboard`.
- `cloudflare.visibility`: `private` (default) or `public`; this is a dashboard label, not Cloudflare provisioning.

Configuration changes appear after you click Refresh. The dashboard checks service status when a tab opens or when you refresh; it does not poll continuously.
