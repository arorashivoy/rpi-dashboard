# User services

The project provides two user services:

- `rpi-dashboard.service` runs the dashboard.
- `rpi-dashboard-tunnel.service` runs the locally-managed Cloudflare Tunnel defined in `~/.cloudflared/rpi-dashboard.yml`.

Install or update both units from the project directory:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rpi-dashboard.service systemd/rpi-dashboard-tunnel.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard.service rpi-dashboard-tunnel.service
```

Check their state and logs with:

```sh
systemctl --user status rpi-dashboard.service rpi-dashboard-tunnel.service
journalctl --user -u rpi-dashboard.service -u rpi-dashboard-tunnel.service -f
```

After editing the Cloudflare Tunnel configuration, validate it and restart only the Tunnel service:

```sh
cloudflared --config ~/.cloudflared/rpi-dashboard.yml tunnel ingress validate
systemctl --user restart rpi-dashboard-tunnel.service
```

The Waypoint Tunnel is managed by a separate project and unit. It is not started or stopped by these units.
