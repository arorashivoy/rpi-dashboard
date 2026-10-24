# Start the dashboard zrok share at boot

This service starts a named public zrok share for the dashboard. It starts after `rpi-dashboard.service` and restarts if zrok exits.

Run these commands as the same Pi user that owns the dashboard and zrok environment:

```sh
zrok2 enable
zrok2 create name pi-dashboard
mkdir -p ~/.config/systemd/user
mkdir -p ~/.config
install -m 600 /dev/null ~/.config/rpi-dashboard-zrok.env
nano ~/.config/rpi-dashboard-zrok.env
```

Add this line to `~/.config/rpi-dashboard-zrok.env`. Use your own unique credentials. Do not use a colon in either value.

```text
ZROK_BASIC_AUTH=your-user:use-a-unique-password
```

Install and enable both user services:

```sh
cp systemd/rpi-dashboard.service ~/.config/systemd/user/
cp systemd/rpi-dashboard-zrok.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rpi-dashboard.service rpi-dashboard-zrok.service
```

Check both units and read the zrok log to find its public URL:

```sh
systemctl --user status rpi-dashboard.service rpi-dashboard-zrok.service
journalctl --user -u rpi-dashboard-zrok.service -f
```

The unit expects the dashboard at `%h/projects/rpi-dashboard` and zrok2 on the user's `PATH`. If your checkout path differs, update `WorkingDirectory`. If zrok2 is not found, replace `/usr/bin/env zrok2` in `ExecStart` with the absolute path from `command -v zrok2`.

The zrok username and password are passed to zrok2 as command-line arguments. Local users with process inspection access may see them. Keep the environment file mode `600` and use a dedicated password for this share.