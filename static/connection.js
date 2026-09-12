const configInput = document.querySelector("#connectionConfig");
const testButton = document.querySelector("#connectionBtn");
const clearButton = document.querySelector("#connectionClear");
const pasteButton = document.querySelector("#connectionPaste");
const charCount = document.querySelector("#connectionCharCount");
const output = document.querySelector("#connectionResult");

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatMs(value) {
    return value == null ? "N/A" : `${value} ms`;
}

function serviceState(result) {
    if (!result || result.status !== "ok") {
        return '<span class="status failed">FAILED</span>';
    }

    return '<span class="status online">ONLINE</span>';
}

function updateCharacterCount() {
    const length = configInput?.value.length || 0;

    if (charCount) {
        charCount.textContent = `${length.toLocaleString()} chars`;
    }
}

function renderServices(services) {
    const rows = [
        ["Instagram", services?.instagram],
        ["YouTube", services?.youtube],
        ["Telegram", services?.telegram],
    ];

    return `
        <section class="detail-card service-card">
            <div class="panel-head">
                <div>
                    <span class="eyebrow">SERVICE LATENCY</span>
                    <h3>Service reachability from VPS</h3>
                </div>
            </div>
            <div class="detail-grid">
                ${rows.map(([name, result]) => `
                    <div class="detail-item">
                        <span>${escapeHtml(name)}</span>
                        <b>${formatMs(result?.latency_ms)}</b>
                        <small>${serviceState(result)} · response ${formatMs(result?.response_ms)}</small>
                        <small>min ${formatMs(result?.min_ms)} · max ${formatMs(result?.max_ms)} · jitter ${formatMs(result?.jitter_ms)}</small>
                        ${result?.http_status ? `<small>HTTP ${escapeHtml(result.http_status)}</small>` : ""}
                        ${result?.error ? `<small>${escapeHtml(result.error)}</small>` : ""}
                    </div>
                `).join("")}
            </div>
            <p class="muted">
                These measurements are direct HTTPS reachability checks from the idontScanner VPS.
                They are not routed through the supplied configuration.
            </p>
        </section>
    `;
}

function renderConnectionQuality(quality) {
    if (!quality || quality.status === "unavailable") {
        return;
    }

    const values = {
        qualityDownload: quality.download_mbps,
        qualityUpload: quality.upload_mbps,
        qualityLatency: quality.latency_ms,
        qualityJitter: quality.jitter_ms,
    };

    Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value ?? "—";
    });

    const note = document.getElementById("qualityNote");
    if (note) {
        note.textContent = quality.error
            ? quality.error
            : `${quality.provider} · ${quality.samples} samples · ${quality.duration_ms} ms`;
    }
}

function renderConnection(data) {
    const config = data.config || {};
    const fields = [
        ["Protocol", config.protocol],
        ["Host", config.host],
        ["Port", config.port],
        ["Transport", config.network],
        ["Security", config.security],
        ["SNI", config.sni],
        ["ALPN", config.alpn],
        ["IP", data.ip],
        ["DNS", formatMs(data.dns_ms)],
        ["TCP Connect", formatMs(data.tcp_ms)],
        ["TLS Handshake", formatMs(data.tls_ms)],
        ["Total", formatMs(data.latency_ms)],
        ["TLS Version", data.tls_version],
        ["Cipher", data.cipher],
        ["Path", config.path],
        ["Service Name", config.service_name],
        ["Host Header", config.host_header],
        ["Method", config.method],
        ["Remark", config.remark],
        ["Error", data.error],
    ];

    const visibleFields = fields.filter(([, value]) => value !== undefined && value !== null && value !== "");

    return `
        <span class="eyebrow">ENDPOINT DIAGNOSTICS</span>
        <h2>${data.status === "ok" || data.status === "resolved" ? "Configuration detected" : "Diagnostic failed"}</h2>
        <div class="detail-grid">
            ${visibleFields.map(([key, value]) => `
                <div class="detail-item">
                    <span>${escapeHtml(key)}</span>
                    <b>${escapeHtml(value ?? "N/A")}</b>
                </div>
            `).join("")}
        </div>
        ${data.transport_note ? `<p class="muted connection-transport-note">${escapeHtml(data.transport_note)}</p>` : ""}
        ${renderServices(data.service_tests)}
    `;
}

testButton?.addEventListener("click", async () => {
    const config = configInput.value.trim();

    if (!config) {
        output.textContent = "Paste a supported configuration first.";
        configInput.focus();
        return;
    }

    testButton.disabled = true;
    output.textContent = "Testing endpoint and service reachability…";

    try {
        const response = await fetch(`${ID.base}/api/connection-check`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                csrf: ID.csrf,
                config,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Connection test failed");
        }

        renderConnectionQuality(data.connection_quality);
        output.innerHTML = renderConnection(data);
    } catch (error) {
        output.textContent = error.message;
    } finally {
        testButton.disabled = false;
    }
});

clearButton?.addEventListener("click", () => {
    configInput.value = "";
    updateCharacterCount();
    output.textContent = "No test yet.";
    configInput.focus();
});

pasteButton?.addEventListener("click", async () => {
    try {
        const text = await navigator.clipboard.readText();
        configInput.value = text.trim();
        updateCharacterCount();
        configInput.focus();
    } catch {
        configInput.focus();
    }
});

configInput?.addEventListener("input", updateCharacterCount);
updateCharacterCount();
