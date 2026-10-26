const serviceList = document.querySelector("#service-list");
const toast = document.querySelector("#toast");
let apps = [];
let toastTimer;
let lastRenderedApps = "";
let refreshInFlight = false;
const refreshButton = document.querySelector("#refresh");

const icons = {
    launch: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>',
};

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
}

function serviceCard(app, index) {
    const state = app.running ? "running" : "stopped";
    const mode = app.kind === "systemd" ? "SYSTEMD" : app.kind === "docker" ? "DOCKER" : "PROCESS";
    const localLink = app.local_url
        ? `<a class="endpoint" href="${escapeHtml(app.local_url)}" target="_blank" rel="noreferrer"><span class="endpoint-symbol">↗</span>${escapeHtml(app.local_url)}</a>`
        : '<span class="endpoint endpoint-muted">No local URL configured</span>';
    const cloudflareLink = app.cloudflare_url
        ? `<a class="cloudflare-link" href="${escapeHtml(app.cloudflare_url)}" target="_blank" rel="noreferrer"><span class="endpoint-symbol">↗</span>${escapeHtml(app.cloudflare_url)} · ${escapeHtml(app.cloudflare_visibility || "private").toUpperCase()}</a>`
        : "";
    const message = app.error ? `<p class="service-error">${escapeHtml(app.error)}</p>` : "";
    const launchButton = app.disabled
        ? `<button class="action-button launch" type="button" disabled title="Configure a start command first">${icons.launch}<span>CONFIGURE</span></button>`
        : `<button class="action-button launch" data-action="start" data-id="${escapeHtml(app.id)}" title="Launch service">${icons.launch}<span>LAUNCH</span></button>`;
    const serviceActions = `<div class="service-actions">${app.managed === false ? "" : app.running
        ? `<button class="action-button stop" data-action="stop" data-id="${escapeHtml(app.id)}" title="Stop service">${icons.stop}<span>STOP</span></button>`
        : launchButton}</div>`;

    return `<article class="service-row ${state}" style="--row-index:${index}">
    <div class="service-main">
      <span class="state-indicator" aria-label="${state}"></span>
      <div class="service-title"><h3>${escapeHtml(app.name)}</h3><p>${escapeHtml(app.description || mode)}</p></div>
      <span class="kind-tag">${mode}</span>
    </div>
    <div class="service-meta">
      <div class="port-block"><span>PORT</span><strong>${app.port ? escapeHtml(app.port) : "—"}</strong></div>
      <div class="link-block"><span>ADDRESS</span>${localLink}${cloudflareLink}</div>
    </div>
    ${message}
    ${serviceActions}
  </article>`;
}

function render() {
    serviceList.innerHTML = apps.length
        ? apps.map(serviceCard).join("")
        : '<div class="empty-state">No services configured. Add entries to apps.json.</div>';
    document.querySelector("#running-count").textContent = apps.filter((app) => app.running).length;
    document.querySelector("#published-count").textContent = apps.filter((app) => app.cloudflare_url).length;
    document.querySelector("#updated-at").textContent = `UPDATED ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function formatBytes(bytes) {
    const gib = bytes / 2 ** 30;
    return gib >= 1 ? `${gib.toFixed(1)}G` : `${Math.round(bytes / 2 ** 20)}M`;
}

function formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

async function loadStats() {
    const target = document.querySelector("#nerd-stats");
    try {
        const response = await fetch("/api/stats", { cache: "no-store" });
        if (!response.ok) throw new Error();
        const s = await response.json();
        const parts = [];
        if (s.load) parts.push(`LOAD ${s.load.map((value) => value.toFixed(2)).join(" ")}`);
        if (s.ram) parts.push(`RAM ${formatBytes(s.ram.used)}/${formatBytes(s.ram.total)}`);
        if (s.swap) parts.push(`SWAP ${formatBytes(s.swap.used)}/${formatBytes(s.swap.total)}`);
        if (s.disk) parts.push(`DISK ${formatBytes(s.disk.used)}/${formatBytes(s.disk.total)}`);
        if (s.temp_c != null) parts.push(`${s.temp_c.toFixed(1)}°C`);
        if (s.freq_mhz != null) parts.push(`${Math.round(s.freq_mhz)} MHz`);
        if (s.uptime_s != null) parts.push(`UP ${formatUptime(s.uptime_s)}`);
        target.textContent = parts.join(" · ");
    } catch {
        target.textContent = "";
    }
}

async function refresh(reloadConfig = false) {
    if (refreshInFlight) return;
    refreshInFlight = true;
    refreshButton.disabled = true;
    loadStats();
    try {
        const response = await fetch(reloadConfig ? "/api/reload" : "/api/apps", {
            cache: "no-store",
            method: reloadConfig ? "POST" : "GET",
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || `Dashboard returned ${response.status}`);
        const nextApps = body.apps || [];
        const nextSnapshot = JSON.stringify(nextApps);
        apps = nextApps;
        if (nextSnapshot !== lastRenderedApps) {
            lastRenderedApps = nextSnapshot;
            render();
        } else {
            document.querySelector("#updated-at").textContent = `UPDATED ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
        }
        if (reloadConfig) showToast("apps.json reloaded.");
    } catch (error) {
        document.querySelector("#updated-at").textContent = "CONNECTION LOST";
        showToast(error.message);
    } finally {
        refreshInFlight = false;
        refreshButton.disabled = false;
    }
}

function showToast(message) {
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 4200);
}

serviceList.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const { action, id } = button.dataset;
    button.disabled = true;
    button.classList.add("busy");
    try {
        const response = await fetch(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: "POST" });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "Action failed");
        const messages = { start: "Service started.", stop: "Service stopped." };
        showToast(messages[action]);
        apps = apps.map((app) => app.id === id ? body.app : app);
        lastRenderedApps = JSON.stringify(apps);
        render();
    } catch (error) {
        showToast(error.message);
    } finally {
        button.disabled = false;
        button.classList.remove("busy");
    }
});

refreshButton.addEventListener("click", () => refresh(true));
refresh();
