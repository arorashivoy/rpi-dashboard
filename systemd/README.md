# Cloudflare Tunnel user service

This dashboard Tunnel uses one `cloudflared` process for its configured application hostnames. Store the locally-managed Tunnel configuration and credentials in `~/.cloudflared/` with permissions restricted to the Pi user. The YAML config must include the Tunnel UUID, credentials file, each hostname-to-origin ingress rule, and a final `http_status:404` rule. Other projects can keep their own Tunnel services; the Pi's existing Waypoint Tunnel is separate.

Install or update the unit as the Pi user:

```sh
mkdir -p ~/.config/systemd/user
cp systemd/rpi-dashboard-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard-tunnel.service
```

After changing the Tunnel configuration:

```sh
systemctl --user restart rpi-dashboard-tunnel.service
systemctl --user status rpi-dashboard-tunnel.service
```

To remove the old dashboard zrok unit, disable it and remove its unit and environment file:

```sh
systemctl --user disable --now rpi-dashboard-zrok.service
rm -f ~/.config/systemd/user/rpi-dashboard-zrok.service
rm -f ~/.config/rpi-dashboard-zrok.env
systemctl --user daemon-reload
```

Do not remove `~/.config/zrok` or disable zrok account-wide until you have confirmed no other project uses it.
