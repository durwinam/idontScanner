const historyList = document.querySelector("#historyList");
const historyDialog = document.querySelector("#historyDialog");
const historyDetails = document.querySelector("#historyDetails");

const ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4.2 4.2L19 6.5"/></svg>',
    failure: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>',
    latency: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/></svg>',
    eye: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 12s3.2-6 9-6 9 6 9 6-3.2 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></svg>',
    globe: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.7 2.5 4 5.3 4 8.5s-1.3 6-4 8.5c-2.7-2.5-4-5.3-4-8.5s1.3-6 4-8.5Z"/></svg>',
};

function icon(name) {
    return ICONS[name] || "";
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatNumber(value) {
    return value == null ? "N/A" : Number(value).toLocaleString();
}

function formatMs(value) {
    return value == null ? "N/A" : `${value} ms`;
}

function renderStat(type, value, label) {
    const statIcon = type === "ok"
        ? icon("success")
        : type === "bad"
            ? icon("failure")
            : icon("latency");

    return `
        <span class="history-stat history-stat--${type}">
            <span class="history-stat-icon">${statIcon}</span>
            <span>${escapeHtml(value)}</span>
            <small>${escapeHtml(label)}</small>
        </span>
    `;
}

async function loadHistory() {
    try {
        const response = await fetch(`${ID.base}/api/history`, {
            cache: "no-store",
        });

        if (!response.ok) {
            throw new Error("Unable to load history.");
        }

        const rows = await response.json();

        historyList.innerHTML = rows.length
            ? rows.map((row) => `
                <div class="history-item">
                    <div>
                        <b>#${escapeHtml(row.id)}</b>
                        <small>${escapeHtml(new Date(row.started_at * 1000).toLocaleString())}</small>
                    </div>
                    <span>${formatNumber(row.total)} targets</span>
                    ${renderStat("ok", row.ok, "healthy")}
                    ${renderStat("bad", row.failed, "failed")}
                    ${renderStat("latency", formatMs(row.average_ms), "average")}
                    <button
                        class="more history-action"
                        data-id="${escapeHtml(row.id)}"
                        title="View scan details"
                        type="button"
                    >
                        ${icon("eye")}
                        <span>View</span>
                    </button>
                </div>
            `).join("")
            : '<div class="empty">No scans yet.</div>';
    } catch (error) {
        historyList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }
}

historyList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-id]");

    if (!button) {
        return;
    }

    button.disabled = true;

    try {
        const response = await fetch(
            `${ID.base}/api/history/${encodeURIComponent(button.dataset.id)}`,
            { cache: "no-store" },
        );

        if (!response.ok) {
            throw new Error("Unable to load scan details.");
        }

        const rows = await response.json();

        historyDetails.innerHTML = `
            <span class="eyebrow">SCAN #${escapeHtml(button.dataset.id)}</span>
            <div class="history-details-heading">
                <div class="mini-icon">${icon("globe")}</div>
                <div>
                    <h2>Observed results</h2>
                    <span class="muted">Raw measurements from the selected scan batch.</span>
                </div>
            </div>
            <div class="results">
                ${rows.map((row) => `
                    <div class="result-row">
                        <div class="result-main">
                            <div class="mini-icon">${icon("globe")}</div>
                            <div>
                                <b>${escapeHtml(row.label)}</b>
                                <small>${escapeHtml(row.domain)}:443</small>
                            </div>
                        </div>
                        <div class="result-right">
                            <span class="status ${escapeHtml(row.status)}">
                                ${escapeHtml(row.status.replaceAll("_", " "))}
                            </span>
                            <strong>
                                ${escapeHtml(row.latency_ms ?? "—")}${row.latency_ms != null ? " ms" : ""}
                            </strong>
                            <small>${escapeHtml(row.tls_version ?? "N/A")}</small>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;

        historyDialog.showModal();
    } catch (error) {
        historyDetails.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
        historyDialog.showModal();
    } finally {
        button.disabled = false;
    }
});

document.querySelector("#historyClose")?.addEventListener("click", () => {
    historyDialog.close();
});

historyDialog?.addEventListener("click", (event) => {
    if (event.target === historyDialog) {
        historyDialog.close();
    }
});

loadHistory();
