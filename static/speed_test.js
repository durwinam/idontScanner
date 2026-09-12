const speedStart = document.querySelector("#speedStart");
const speedState = document.querySelector("#speedState");
const speedStage = document.querySelector("#speedStage");
const speedProgress = document.querySelector("#speedProgress");
const speedShell = document.querySelector("#speedTestShell");
const speedResults = document.querySelector("#speedResults");
function setStage(label, progress) { speedState.textContent = label; speedStage.textContent = progress >= 100 ? "Test complete." : "Measuring direct VPS network performance…"; speedProgress.style.width = `${progress}%`; }
speedStart?.addEventListener("click", async () => {
    speedStart.disabled = true; speedShell.classList.add("testing"); speedResults.classList.add("hidden");
    setStage("Preparing test…", 8); await new Promise(r => setTimeout(r, 450));
    setStage("Measuring latency…", 20); await new Promise(r => setTimeout(r, 450));
    setStage("Testing download…", 42); await new Promise(r => setTimeout(r, 450));
    setStage("Testing upload…", 70);
    try {
        const response = await fetch(`${ID.base}/api/vps-speed-test`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({csrf:ID.csrf})});
        const data = await response.json(); if (!response.ok) throw new Error(data.error || "Speed test failed.");
        setStage("Finalizing results…", 92); await new Promise(r => setTimeout(r, 400));
        document.querySelector("#speedDownload").textContent=data.download_mbps; document.querySelector("#speedUpload").textContent=data.upload_mbps; document.querySelector("#speedLatency").textContent=data.latency_ms; document.querySelector("#speedJitter").textContent=data.jitter_ms;
        document.querySelector("#speedProvider").textContent=data.provider; document.querySelector("#speedSamples").textContent=data.samples; document.querySelector("#speedDuration").textContent=`${data.duration_ms} ms`;
        speedResults.classList.remove("hidden"); setStage("Test complete ✓", 100);
    } catch (error) { setStage(error.message, 0); }
    finally { speedShell.classList.remove("testing"); speedStart.disabled=false; }
});
