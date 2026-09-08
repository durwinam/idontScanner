const $ = (selector) => document.querySelector(selector);
const base = window.IDONT.base;
const csrf = window.IDONT.csrf;

const scanBtn = $("#scanBtn");
const state = $("#scanState");
const results = $("#results");

function setRow(row, data) {
    const status = row.querySelector(".status");
    const latency = row.querySelector(".latency");
    const tls = row.querySelector(".tls");

    status.className = "status " + data.status;
    status.textContent =
        data.status === "ok"
            ? "ONLINE"
            : data.status.replace("_", " ").toUpperCase();

    latency.textContent =
        data.latency_ms != null ? data.latency_ms + " ms" : "—";

    tls.textContent = data.tls_version || "—";
}

scanBtn.onclick = async () => {
    scanBtn.disabled = true;
    state.textContent = "Scanning approved targets…";

    [...results.querySelectorAll(".row")].forEach((row) => {
        row.querySelector(".status").className = "status testing";
        row.querySelector(".status").textContent = "TESTING";
        row.querySelector(".latency").textContent = "…";
        row.querySelector(".tls").textContent = "…";
    });

    try {
        const response = await fetch(base + "/api/scan", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ csrf }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Scan failed");
        }

        data.results.forEach((item) => {
            const row = [...results.querySelectorAll(".row")].find(
                (element) => element.dataset.domain === item.domain
            );

            if (row) {
                setRow(row, item);
            }
        });

        $("#total").textContent = data.total;
        $("#healthy").textContent = data.ok;

        const best = data.results.find((item) => item.status === "ok");
        $("#best").textContent = best ? best.latency_ms + " ms" : "—";
        $("#duration").textContent = data.duration_ms + " ms";

        state.textContent =
            `Completed · ${data.ok}/${data.total} healthy`;

        loadHistory();
    } catch (error) {
        state.textContent = error.message;
    } finally {
        scanBtn.disabled = false;
    }
};

$("#search").oninput = (event) => {
    const query = event.target.value.toLowerCase();

    results.querySelectorAll(".row").forEach((row) => {
        row.style.display = row.dataset.domain.includes(query) ? "" : "none";
    });
};

$("#addBtn").onclick = () => $("#addDialog").showModal();

$(".close").onclick = () => $("#addDialog").close();

$("#saveDomain").onclick = async (event) => {
    event.preventDefault();

    const domain = $("#domain").value.trim();
    const label = $("#label").value.trim() || "Custom";

    const response = await fetch(base + "/api/domains", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            csrf,
            domain,
            label,
        }),
    });

    const data = await response.json();

    if (response.ok) {
        location.reload();
    } else {
        alert(data.error || "Unable to add domain");
    }
};

results.onclick = async (event) => {
    const id = event.target.dataset.delete;

    if (!id) {
        return;
    }

    if (!confirm("Delete this custom domain?")) {
        return;
    }

    const response = await fetch(base + "/api/domains/" + id, {
        method: "DELETE",
        headers: {
            "x-csrf-token": csrf,
        },
    });

    if (response.ok) {
        location.reload();
    } else {
        alert(
            (await response.json()).error ||
            "Unable to delete"
        );
    }
};

async function loadHistory() {
    const response = await fetch(base + "/api/history");

    if (!response.ok) {
        return;
    }

    const data = await response.json();

    $("#history").innerHTML = data.length
        ? data
            .map(
                (item) =>
                    `<div class="history-item">
                        <span>
                            #${item.id} · ${new Date(
                                item.started_at * 1000
                            ).toLocaleString()}
                        </span>
                        <span>
                            ${item.ok}/${item.total} healthy ·
                            ${item.duration_ms.toFixed(0)} ms
                        </span>
                    </div>`
            )
            .join("")
        : '<div class="history-item">' +
          '<span class="muted">No scans yet.</span>' +
          "</div>";
}

loadHistory();
