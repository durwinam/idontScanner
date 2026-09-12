const mode = window.IDONT_MODE || "domain";
const tabs = [...document.querySelectorAll(".scanner-tabs a")];
const results = document.querySelector("#results");
const detailsDialog = document.querySelector("#detailsDialog");
const detailContent = document.querySelector("#detailContent");

const SERVICE_MODES = new Set(["domain", "sni", "cdn"]);

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function valueOrFallback(value) {
    return value == null || value === "" ? "N/A" : value;
}

function setScannerMode(name) {
    document.querySelector("#modeDomain")?.classList.toggle("hidden", name !== "domain");
    document.querySelector("#domainTargetCard")?.classList.toggle("hidden", name !== "domain");
    document.querySelector("#modeSni")?.classList.toggle("hidden", name !== "sni");
    document.querySelector("#modeCdn")?.classList.toggle("hidden", name !== "cdn");
}

function setResultRow(row, data) {
    const status = row.querySelector(".status");
    const latency = row.querySelector(".latency");
    const tls = row.querySelector(".tls");

    status.className = `status ${data.status}`;
    status.textContent = data.status === "ok"
        ? "ONLINE"
        : data.status.replaceAll("_", " ").toUpperCase();
    latency.textContent = data.latency_ms != null ? `${data.latency_ms} ms` : "—";
    tls.textContent = data.tls_version || "—";
    row.dataset.result = JSON.stringify(data);
}

function renderDetails(data) {
    const fields = [
        ["Status", data.status],
        ["IP", data.ip],
        ["Latency", data.latency_ms != null ? `${data.latency_ms} ms` : null],
        ["DNS", data.dns_ms != null ? `${data.dns_ms} ms` : null],
        ["TCP", data.tcp_ms != null ? `${data.tcp_ms} ms` : null],
        ["TLS", data.tls_ms != null ? `${data.tls_ms} ms` : null],
        ["TLS Version", data.tls_version],
        ["ALPN", data.alpn],
        ["Cipher", data.cipher],
        ["Certificate Subject", data.cert_subject],
        ["Certificate Issuer", data.cert_issuer],
        ["Certificate Expiry", data.cert_expires],
        ["SAN", data.cert_san],
        ["Error", data.error],
    ];

    return `
        <span class="eyebrow">OBSERVED CONNECTION</span>
        <h2>${escapeHtml(data.domain || data.target || "Target")}</h2>
        <div class="detail-grid">
            ${fields.map(([key, value]) => `
                <div class="detail-item">
                    <span>${escapeHtml(key)}</span>
                    <b>${escapeHtml(valueOrFallback(value))}</b>
                </div>
            `).join("")}
        </div>
    `;
}

async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || "Request failed.");
    }

    return data;
}

tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.mode === mode);
});
setScannerMode(SERVICE_MODES.has(mode) ? mode : "domain");

document.querySelector("#scanBtn")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const state = document.querySelector("#scanState");

    button.disabled = true;
    const customEnabled = document.querySelector("#customTargetToggle")?.getAttribute("aria-pressed") === "true";
    const customTarget = document.querySelector("#customTargetIp")?.value.trim() || "";

    if (customEnabled && !customTarget) {
        state.textContent = "Enter a custom target IP first.";
        button.disabled = false;
        document.querySelector("#customTargetIp")?.focus();
        return;
    }

    state.textContent = customEnabled
        ? "Scanning all enabled targets via the custom IP…"
        : "Scanning real TLS connections…";

    document.querySelectorAll(".result-row").forEach((row) => {
        row.querySelector(".status").className = "status testing";
        row.querySelector(".status").textContent = "TESTING";
        row.querySelector(".latency").textContent = "…";
        row.querySelector(".tls").textContent = "…";
    });

    try {
        const data = await postJson(`${ID.base}/api/scan`, {
            csrf: ID.csrf,
            connect_target: customEnabled ? customTarget : "",
        });

        data.results.forEach((result) => {
            const row = [...document.querySelectorAll(".result-row")]
                .find((item) => item.dataset.domain === result.domain);

            if (row) {
                setResultRow(row, result);
            }
        });

        state.textContent = `Completed · ${data.ok}/${data.total} online · average ${data.average_ms ?? "N/A"} ms · score ${data.score}/100`;
        const scoreBox = document.querySelector("#scanScore");
        if (scoreBox) scoreBox.innerHTML = `<strong>${data.score}/100</strong><span>${escapeHtml(data.score_label)}</span>`;
    } catch (error) {
        state.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

document.querySelector("#search")?.addEventListener("input", (event) => {
    const query = event.target.value.toLowerCase();

    document.querySelectorAll(".result-row").forEach((row) => {
        const domain = row.dataset.domain?.toLowerCase() || "";
        row.style.display = domain.includes(query) ? "" : "none";
    });
});

results?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-details]");

    if (!button) {
        return;
    }

    const row = button.closest(".result-row");
    let data = {};

    try {
        data = JSON.parse(row.dataset.result || "{}");
    } catch {
        data = {};
    }

    data.domain = row.dataset.domain;
    detailContent.innerHTML = Object.keys(data).length > 1
        ? renderDetails(data)
        : '<div class="empty">Run a scan first to see observed connection details.</div>';

    detailsDialog.showModal();
});

document.querySelector("#detailClose")?.addEventListener("click", () => {
    detailsDialog.close();
});

document.querySelector("#sniBtn")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = document.querySelector("#sniResult");

    button.disabled = true;
    output.textContent = "Checking…";

    try {
        const data = await postJson(`${ID.base}/api/sni-check`, {
            csrf: ID.csrf,
            target: document.querySelector("#sniTarget").value,
            sni: document.querySelector("#sniValue").value,
        });

        output.innerHTML = renderDetails(data);
    } catch (error) {
        output.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

document.querySelector("#cdnBtn")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = document.querySelector("#cdnResult");

    button.disabled = true;
    output.textContent = "Inspecting…";

    try {
        const data = await postJson(`${ID.base}/api/cdn-check`, {
            csrf: ID.csrf,
            domain: document.querySelector("#cdnDomain").value,
        });

        output.innerHTML = `${renderDetails(data)}
            <p class="muted">Provider observation: <b>${escapeHtml(valueOrFallback(data.provider_hint))}</b></p>`;
    } catch (error) {
        output.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});


const customTargetToggle = document.querySelector("#customTargetToggle");
customTargetToggle?.addEventListener("click", () => {
    const enabled = customTargetToggle.getAttribute("aria-pressed") === "true";
    customTargetToggle.setAttribute("aria-pressed", String(!enabled));
    customTargetToggle.querySelector(".toggle-label").textContent = enabled ? "VPS MODE" : "CUSTOM IP";
    document.querySelector("#customTargetFields")?.classList.toggle("hidden", enabled);
});
