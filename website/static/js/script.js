let chart;

function calcDew(temp, hum) {
    return temp - ((100 - hum) / 5);
}

function formatTime(ts) {
    return new Date(ts).toLocaleString("de-DE", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
    });
}

// ---------------- SENSOR ----------------
async function loadSensors(from = "", to = "") {
    let url = "/api/sensoren";

    if (from || to) {
        url += `?from=${from}&to=${to}`;
    }

    const res = await fetch(url, { credentials: "include" });
    const data = await res.json();

    if (!data.length) return;

    render(data);
}

function render(data) {
    const last = data[0];

    document.getElementById("temp_in").textContent = last.temp_innen.toFixed(1);
    document.getElementById("temp_out").textContent = last.temp_aussen.toFixed(1);
    document.getElementById("hum_in").textContent = last.hum_innen.toFixed(0);
    document.getElementById("hum_out").textContent = last.hum_aussen.toFixed(0);
    document.getElementById("timestamp").textContent = formatTime(last.timestamp);

    const dewIn = calcDew(last.temp_innen, last.hum_innen);
    const dewOut = calcDew(last.temp_aussen, last.hum_aussen);

    document.getElementById("dew_in").textContent = dewIn.toFixed(1);
    document.getElementById("dew_out").textContent = dewOut.toFixed(1);

    updateStatus(last);
    updateChart(data);
}

// ---------------- STATUS ----------------
function updateStatus(last) {
    const dewIn = calcDew(last.temp_innen, last.hum_innen);
    const dewOut = calcDew(last.temp_aussen, last.hum_aussen);

    const status = document.getElementById("ventilation_status");
    const card = status.parentElement;

    card.classList.remove("good", "bad");

    if (dewOut < dewIn) {
        status.textContent = "✅ Lüften sinnvoll";
        card.classList.add("good");
    } else {
        status.textContent = "❌ Nicht lüften";
        card.classList.add("bad");
    }
}

function updateChart(data) {
    const labels = data.map(d => formatTime(d.timestamp)).reverse();
    const inside = data.map(d => d.temp_innen).reverse();
    const outside = data.map(d => d.temp_aussen).reverse();

    if (chart) chart.destroy();

    chart = new Chart(document.getElementById("tempChart"), {
        type: "line",
        data: {
            labels,
            datasets: [
                { label: "Innen", data: inside, tension: 0.3 },
                { label: "Außen", data: outside, tension: 0.3 }
            ]
        }
    });
}

function applyFilter() {
    const from = document.getElementById("fromTime").value;
    const to = document.getElementById("toTime").value;

    loadSensors(from, to);
}

function resetFilter() {
    document.getElementById("fromTime").value = "";
    document.getElementById("toTime").value = "";

    loadSensors();
}

// ---------------- FAN ----------------
async function loadFan() {
    const res = await fetch("/api/fan", { credentials: "include" });
    const data = await res.json();

    const el = document.getElementById("fan_state");
    el.textContent = data.fan_state;

    el.style.color = data.fan_state === "on" ? "green" : "red";
}

// ---------------- INIT ----------------
loadSensors();
loadFan();

setInterval(() => loadSensors(), 5000);
setInterval(loadFan, 2000);