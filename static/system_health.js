const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const serviceLabels = { api: "API", database: "Database", scanner: "Scanner", telegram: "Telegram" };
function statusRow(label, ok) { return `<div class="health-row"><span class="status-indicator ${ok ? "is-good" : "is-bad"}"></span><b>${esc(label)}</b><span class="health-state">${ok ? "Healthy" : "Not configured"}</span></div>`; }
function metric(label, value) { return `<div class="health-metric"><span>${esc(label)}</span><b>${esc(value)}</b></div>`; }
async function refreshHealth() {
  const button = document.querySelector("#healthRefresh");
  button?.classList.add("is-loading");
  try {
    const response = await fetch(`${ID.base}/api/system/health`, { cache: "no-store", headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Health check failed.");
    document.querySelector("#healthScore").textContent = data.score;
    document.querySelector("#healthLabel").textContent = data.healthy ? "Healthy" : "Attention required";
    document.querySelector("#healthUpdated").textContent = `Checked ${new Date(data.timestamp * 1000).toLocaleTimeString()}`;
    document.querySelector("#healthServices").innerHTML = Object.entries(data.checks).map(([key, value]) => statusRow(serviceLabels[key] || key, value)).join("");
    document.querySelector("#healthResources").innerHTML = [metric("CPU", `${data.resources.cpu}%`), metric("Memory", `${data.resources.memory}%`), metric("Disk", `${data.resources.disk}%`)].join("");
    const log = `${(data.log_bytes / 1024 / 1024).toFixed(1)} / ${(data.log_limit / 1024 / 1024).toFixed(0)} MB`;
    document.querySelector("#healthRuntime").innerHTML = [metric("Uptime", data.uptime), metric("Log size", log), metric("Status", data.healthy ? "Operational" : "Attention")].join("");
  } catch (error) {
    document.querySelector("#healthLabel").textContent = error.message;
  } finally { button?.classList.remove("is-loading"); }
}
document.querySelector("#healthRefresh")?.addEventListener("click", refreshHealth);
refreshHealth();
