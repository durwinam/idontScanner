const resourceState = {
    history: { cpu: [], memory: [], disk: [] },
    maxPoints: 720,
};

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function resourceTone(percent) {
    const value = Number(percent) || 0;

    if (value >= 90) {
        return { color: "#ff4d6d", glow: "rgba(255,77,109,.42)" };
    }
    if (value >= 75) {
        return { color: "#ff9f43", glow: "rgba(255,159,67,.38)" };
    }
    if (value >= 50) {
        return { color: "#d9df55", glow: "rgba(217,223,85,.32)" };
    }
    return { color: "#45e6a8", glow: "rgba(69,230,168,.30)" };
}

function setGauge(id, progressId, percent) {
    const gauge = document.getElementById(id);
    const progress = document.getElementById(progressId);
    if (!gauge || !progress) return;

    const safe = Math.max(0, Math.min(100, Number(percent) || 0));
    const tone = resourceTone(safe);

    progress.style.strokeDasharray = `${safe} 100`;
    progress.style.stroke = `url(#${gauge.dataset.resource}GaugeGradient)`;
    gauge.style.setProperty("--tone", tone.color);
    gauge.style.setProperty("--tone-glow", tone.glow);
    gauge.style.setProperty("--value", `${safe}%`);

    const card = gauge.closest(".resource-card");
    if (card) {
        card.style.setProperty("--tone", tone.color);
        card.style.setProperty("--tone-glow", tone.glow);
    }
}

function chartPath(values, width = 240, height = 70) {
    if (!values.length) return { line: "", fill: "" };

    const min = 0;
    const max = 100;
    const step = values.length === 1 ? width : width / (values.length - 1);
    const points = values.map((value, index) => {
        const x = index * step;
        const clamped = Math.max(min, Math.min(max, value));
        const normalized = (clamped - min) / (max - min);
        const y = height - normalized * (height - 6) - 3;
        return [x, y];
    });

    const line = points
        .map(([x, y], index) => {
            const command = index ? "L" : "M";
            return `${command}${x.toFixed(1)} ${y.toFixed(1)}`;
        })
        .join(" ");
    const fill = `${line} L ${width} ${height} L 0 ${height} Z`;
    return { line, fill };
}

function updateChart(id, values) {
    const svg = document.getElementById(id);
    if (!svg) return;
    const paths = chartPath(values);
    svg.querySelector(".chart-line").setAttribute("d", paths.line);
    svg.querySelector(".chart-fill").setAttribute("d", paths.fill);
}

function pushHistory(name, value) {
    const values = resourceState.history[name];
    values.push(Number(value) || 0);
    if (values.length > resourceState.maxPoints) values.shift();
    updateChart(`${name}Chart`, values);
}

function renderResources(data) {
    setGauge("cpuGauge", "cpuProgress", data.cpu.percent);
    setText("cpuPercent", `${Math.round(data.cpu.percent)}%`);
    setText("cpuMeta", `${data.cpu.cores} cores`);
    setText("loadValue", data.load.toFixed(2));
    setText("processValue", data.processes);

    setGauge("memoryGauge", "memoryProgress", data.memory.percent);
    setText("memoryPercent", `${Math.round(data.memory.percent)}%`);
    setText("memoryMeta", `${data.memory.used_gb} / ${data.memory.total_gb} GB`);
    setText("memoryUsed", `${data.memory.used_gb} GB`);
    const memoryAvailable = Math.max(
        0,
        data.memory.total_gb - data.memory.used_gb,
    );
    setText("memoryAvailable", `${memoryAvailable.toFixed(2)} GB`);

    setGauge("diskGauge", "diskProgress", data.disk.percent);
    setText("diskPercent", `${Math.round(data.disk.percent)}%`);
    setText("diskMeta", `${data.disk.used_gb} / ${data.disk.total_gb} GB`);
    setText("diskUsed", `${data.disk.used_gb} GB`);
    setText("diskFree", `${Math.max(0, data.disk.total_gb - data.disk.used_gb).toFixed(2)} GB`);

    setText("uptimeValue", data.uptime);
    setText(
        "networkValue",
        `↓ ${data.network.down_mbps} MB/s   ↑ ${data.network.up_mbps} MB/s`,
    );

    const temperature = data.temperature;
    setText("temperatureValue", temperature == null ? "N/A" : `${temperature}°C`);
    const bar = document.getElementById("temperatureBar");
    if (bar) {
        const temperaturePercent = temperature == null
            ? 0
            : Math.min(100, (temperature / 90) * 100);
        bar.style.width = `${temperaturePercent}%`;
    }

    pushHistory("cpu", data.cpu.percent);
    pushHistory("memory", data.memory.percent);
    pushHistory("disk", data.disk.percent);
}

async function refreshResources() {
    try {
        const response = await fetch(`${ID.base}/api/system/stats`, {
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        if (!response.ok) throw new Error("Unable to load server resources.");
        renderResources(await response.json());
    } catch (error) {
        console.warn("Server resources:", error.message);
    }
}

const range = document.getElementById("resourceRange");
range?.addEventListener("change", () => {
    resourceState.maxPoints = Number(range.value) || 60;
    Object.keys(resourceState.history).forEach((key) => {
        resourceState.history[key] = resourceState.history[key].slice(-resourceState.maxPoints);
        updateChart(`${key}Chart`, resourceState.history[key]);
    });
});

refreshResources();
window.setInterval(refreshResources, 5000);

async function runQuickScan() {
    const state = document.querySelector("#dashState");
    const output = document.querySelector("#dashResult");
    if (!state || !output) return;

    state.textContent = "Scanning approved targets…";

    try {
        const response = await fetch(`${ID.base}/api/scan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ csrf: ID.csrf }),
        });
        const data = await response.json();

        if (!response.ok) throw new Error(data.error || "Scan failed.");

        state.textContent = `Completed · ${data.ok}/${data.total} healthy`;
        output.innerHTML = `
            <div class="detail-grid">
                <div class="detail-item"><span>Online</span><b>${data.ok}</b></div>
                <div class="detail-item"><span>Failed</span><b>${data.failed}</b></div>
                <div class="detail-item">
                    <span>Average</span>
                    <b>${data.average_ms ?? "N/A"} ms</b>
                </div>
                <div class="detail-item"><span>Duration</span><b>${data.duration_ms} ms</b></div>
            </div>
        `;
    } catch (error) {
        state.textContent = error.message;
    }
}

document.querySelector("#quickScan")?.addEventListener("click", runQuickScan);
