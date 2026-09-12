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
    return code.toUpperCase().replace(/./g, char => String.fromCodePoint(char.charCodeAt(0) + 127397));
}

function setState(text) {
    if (state) state.textContent = text;
}

function renderInfo(data) {
    summary.classList.add("hidden");
    permanent.classList.add("hidden");
    table.innerHTML = `
        <div class="check-info-grid">
            <div class="detail-item"><span>Hostname</span><b>${escapeHtml(data.hostname)}</b></div>
            <div class="detail-item"><span>DNS lookup</span><b>${formatMs(data.dns_ms)}</b></div>
            <div class="detail-item"><span>IPv4 / IPv6</span><b>${data.ips?.length || 0} addresses</b></div>
            <div class="detail-item full"><span>Addresses</span><b>${(data.ips || []).map(escapeHtml).join(" · ") || "N/A"}</b></div>
        </div>
        <div class="check-host-ptr-list">
            ${(data.reverse_dns || []).map(item => `<div class="check-host-row"><span>${escapeHtml(item.ip)}</span><b>${escapeHtml(item.ptr || "No PTR")}</b></div>`).join("")}
        </div>
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
            <div class="check-node-location"><span class="node-flag">${flag(item.country_code)}</span><div><b>${escapeHtml(item.country)}, ${escapeHtml(item.city)}</b><small>${escapeHtml(item.id)} · ${escapeHtml(item.asn || "")}</small></div></div>
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
    setState("Resolving target information…");
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

    setState(`Starting ${activeType.toUpperCase()} from global nodes…`);
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
        setState(`Checking global nodes · ${data.completed}/${data.total} completed…`);
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
