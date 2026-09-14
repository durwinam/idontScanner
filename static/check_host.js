const targetInput = document.querySelector("#checkHostTarget");
const runButton = document.querySelector("#checkHostRun");
const state = document.querySelector("#checkHostState");
const table = document.querySelector("#checkHostTable");
const summary = document.querySelector("#checkHostSummary");
const permanent = document.querySelector("#checkHostPermanent");
const portWrap = document.querySelector("#checkHostPortWrap");
const portInput = document.querySelector("#checkHostPort");
let activeType = "info";
let activeNodeGroup = "global";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatMs(value) {
    return value == null ? "—" : `${value} ms`;
}

function flag(code) {
    if (!code || code.length !== 2) return "";
    const normalized = code.toUpperCase();

    if (normalized === "IR") {
        return `<img class="node-flag node-flag--image" src="${ID.base}/static/icons/iran-lion-sun.svg" alt="Iran">`;
    }

    // Do not rely on Windows/Android emoji fonts for country flags.
    // Check-Host exposes ISO country codes, so render a real SVG flag for every node.
    const src = `https://cdn.ipwhois.io/flags/${normalized.toLowerCase()}.svg`;
    return `<img class="node-flag node-flag--image node-flag--remote" src="${src}" alt="${normalized}" loading="lazy" referrerpolicy="no-referrer">`;
}

function tr(key, fallback) {
    return window.IDONT_T ? window.IDONT_T(key, fallback) : (fallback || key);
}

function setState(text) {
    if (state) state.textContent = text;
}

function renderInfo(data) {
    summary.classList.add("hidden");
    permanent.classList.add("hidden");

    const geo = Array.isArray(data.geo) ? data.geo : [];
    const geoCards = geo.map(item => {
        const provider = item.organization || item.isp || "—";
        const location = item.location || [item.city, item.region, item.country].filter(Boolean).join(", ") || "—";
        const networkType = item.network_type || (item.hosting ? tr("Hosting / Data Center", "Hosting / Data Center") : "—");
        const asn = item.asn || "—";
        return `
            <article class="check-geo-card">
                <div class="check-geo-head">
                    <div class="check-geo-location">${flag(item.country_code)}<div><strong>${escapeHtml(location)}</strong><small>${escapeHtml(item.country || "")}</small></div></div>
                    <span class="check-geo-type">${escapeHtml(networkType)}</span>
                </div>
                <div class="check-geo-grid">
                    <div class="detail-item"><span>IP</span><b>${escapeHtml(item.ip)}</b></div>
                    <div class="detail-item"><span>Datacenter / Provider</span><b>${escapeHtml(provider)}</b></div>
                    <div class="detail-item"><span>ISP</span><b>${escapeHtml(item.isp || provider)}</b></div>
                    <div class="detail-item"><span>ASN</span><b>${escapeHtml(asn)}</b></div>
                </div>
            </article>
        `;
    }).join("");

    const geoSection = geoCards
        ? `<section class="check-geo-section"><div class="check-info-section-head"><span class="eyebrow">TARGET LOCATION</span><strong>IP / Domain location</strong></div>${geoCards}</section>`
        : `<div class="check-info-unavailable">Location and datacenter information is temporarily unavailable. DNS and local host information are still available.</div>`;

    table.innerHTML = `
        <div class="check-info-grid">
            <div class="detail-item"><span>Hostname / Target</span><b>${escapeHtml(data.hostname)}</b></div>
            <div class="detail-item"><span>DNS lookup</span><b>${formatMs(data.dns_ms)}</b></div>
            <div class="detail-item"><span>Resolved addresses</span><b>${data.ips?.length || 0}</b></div>
            <div class="detail-item full"><span>Addresses</span><b>${(data.ips || []).map(escapeHtml).join(" · ") || "N/A"}</b></div>
        </div>
        ${geoSection}
        <section class="check-host-ptr-list">
            <div class="check-info-section-head"><span class="eyebrow">REVERSE DNS</span><strong>PTR records</strong></div>
            ${(data.reverse_dns || []).map(item => `<div class="check-host-row"><span>${escapeHtml(item.ip)}</span><b>${escapeHtml(item.ptr || "No PTR")}</b></div>`).join("")}
        </section>
    `;
}

function renderResults(data) {
    summary.classList.remove("hidden");
    document.querySelector("#checkNodes").textContent = `${data.completed}/${data.total}`;
    document.querySelector("#checkOnline").textContent = `${data.online} online`;
    document.querySelector("#checkAverage").textContent = data.average_ms == null ? "—" : data.average_ms;
    const score = data.total ? Math.round((data.online / data.total) * 100) : 0;
    document.querySelector("#checkScore").textContent = `${score}/100`;
    document.querySelector("#checkSummaryText").textContent = score >= 90 ? "Excellent global reachability" : score >= 60 ? "Needs attention" : "Critical reachability";

    table.innerHTML = data.results.map(item => {
        const status = item.status === "online" ? "online" : item.status === "pending" ? "testing" : item.status === "unknown" ? "warning" : "failed";
        const metric = activeType === "ping"
            ? `${item.success ?? 0}/${item.total ?? 0} · ${formatMs(item.avg_ms)}`
            : activeType === "dns"
                ? `${(item.a || []).length} A · ${(item.aaaa || []).length} AAAA · TTL ${item.ttl ?? "—"}`
                : formatMs(item.latency_ms);
        const detail = activeType === "ping"
            ? `min ${formatMs(item.min_ms)} · max ${formatMs(item.max_ms)} · loss ${item.loss_percent ?? 100}%`
            : activeType === "http"
                ? `HTTP ${item.http_status ?? "—"} · ${escapeHtml(item.message || "")}`
                : activeType === "dns"
                    ? `${(item.a || []).concat(item.aaaa || []).map(escapeHtml).join(" · ") || "No records"}`
                    : escapeHtml(item.ip || item.error || "");
        return `<div class="check-host-row ${status}">
            <div class="check-node-location">${flag(item.country_code)}<div><b>${escapeHtml(item.country)}, ${escapeHtml(item.city)}</b><small>${escapeHtml(item.id)} · ${escapeHtml(item.asn || "")}</small></div></div>
            <span class="status ${status}">${status.toUpperCase()}</span>
            <strong>${escapeHtml(metric)}</strong>
            <small>${detail}</small>
        </div>`;
    }).join("");
}

async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Request failed.");
    return data;
}

async function runInfo(target) {
    setState(tr("Resolving target information…", "Resolving target information…"));
    const data = await postJson(`${ID.base}/api/check-host/info`, {csrf: ID.csrf, target});
    renderInfo(data);
    setState("Info check complete.");
}

async function runCheck(target) {
    const checkTarget = activeType === "tcp" || activeType === "udp"
        ? `${target}:${Number(portInput.value || 443)}`
        : activeType === "http" && !/^https?:\/\//i.test(target)
            ? `https://${target}`
            : target;

    setState(`Starting ${activeType.toUpperCase()} from ${activeNodeGroup === "iran" ? "Iran" : "global"} nodes…`);
    const started = await postJson(`${ID.base}/api/check-host/start`, {
        csrf: ID.csrf,
        type: activeType,
        target: checkTarget,
        node_group: activeNodeGroup,
    });

    if (started.permanent_link) {
        permanent.href = started.permanent_link;
        permanent.classList.remove("hidden");
    }

    const encodedNodes = encodeURIComponent(JSON.stringify(started.nodes));
    let last = null;
    const startedAt = Date.now();

    while (Date.now() - startedAt < 35_000) {
        const response = await fetch(`${ID.base}/api/check-host/result/${encodeURIComponent(started.request_id)}?type=${encodeURIComponent(activeType)}&nodes=${encodedNodes}`, {cache: "no-store"});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to fetch result.");
        last = data;
        renderResults(data);
        setState(`Checking ${activeNodeGroup === "iran" ? "Iran" : "global"} nodes · ${data.completed}/${data.total} completed…`);
        if (data.complete) break;
        await new Promise(resolve => setTimeout(resolve, 900));
    }

    if (!last) throw new Error("No result returned.");
    setState(`Completed · ${last.online}/${last.total} nodes online.`);
}

runButton?.addEventListener("click", async () => {
    const target = targetInput.value.trim();
    if (!target) {
        targetInput.focus();
        setState("Enter a hostname or IP address first.");
        return;
    }

    runButton.disabled = true;
    table.innerHTML = '<div class="check-host-loading"><span></span><b>Connecting to global nodes…</b></div>';
    try {
        if (activeType === "info") await runInfo(target);
        else await runCheck(target);
    } catch (error) {
        setState(error.message);
        table.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    } finally {
        runButton.disabled = false;
    }
});

document.querySelectorAll(".check-mode").forEach(button => {
    button.addEventListener("click", () => {
        document.querySelectorAll(".check-mode").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        activeType = button.dataset.type;
        portWrap.classList.toggle("hidden", !["tcp", "udp"].includes(activeType));
        setState(activeType === "info" ? "Ready." : `Ready for ${activeType.toUpperCase()} check.`);
    });
});


document.querySelectorAll(".node-group").forEach((button) => {
    button.addEventListener("click", () => {
        document.querySelectorAll(".node-group").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        activeNodeGroup = button.dataset.group || "global";
        setState(activeNodeGroup === "iran" ? "Iran node group selected · 6 nodes." : "Global node group selected.");
    });
});
