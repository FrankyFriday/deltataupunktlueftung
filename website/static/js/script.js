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
    if (!res.ok) return;
    const data = await res.json();

    if (!data.length) return;

    render(data);
}

function render(data) {
    const last = data[0];

    // Dashboard-Ansicht
    const tempIn = document.getElementById("temp_in");
    const tempOut = document.getElementById("temp_out");
    if (tempIn && tempOut) {
        tempIn.textContent = last.temp_innen.toFixed(1);
        tempOut.textContent = last.temp_aussen.toFixed(1);
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

    // Sensoren-Tabelle
    const tableBody = document.getElementById("sensor_table_body");
    if (tableBody) {
        const rows = data.slice(0, 50).map(d => `
            <tr>
                <td>${formatTime(d.timestamp)}</td>
                <td>${d.temp_innen?.toFixed(1) ?? '--'} °C</td>
                <td>${d.temp_aussen?.toFixed(1) ?? '--'} °C</td>
                <td>${d.hum_innen?.toFixed(0) ?? '--'} %</td>
                <td>${d.hum_aussen?.toFixed(0) ?? '--'} %</td>
            </tr>
        `).join("");
        tableBody.innerHTML = rows;
    }
}

// ---------------- STATUS ----------------
function updateStatus(last) {
    const status = document.getElementById("ventilation_status");
    if (!status) return;

    const dewIn = calcDew(last.temp_innen, last.hum_innen);
    const dewOut = calcDew(last.temp_aussen, last.hum_aussen);

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
    const canvas = document.getElementById("tempChart");
    if (!canvas) return;

    const labels = data.map(d => formatTime(d.timestamp)).reverse();
    const inside = data.map(d => d.temp_innen).reverse();
    const outside = data.map(d => d.temp_aussen).reverse();

    if (chart) chart.destroy();

    chart = new Chart(canvas, {
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
    const stateEl = document.getElementById("fan_state");
    if (!stateEl) return;

    try {
        const [fanRes, overrideRes] = await Promise.all([
            fetch("/api/fan", { credentials: "include" }),
            fetch("/api/fan/override", { credentials: "include" })
        ]);

        if (fanRes.ok) {
            const fanData = await fanRes.json();
            stateEl.textContent = fanData.fan_state === "on" ? "AN" : "AUS";
            stateEl.style.color = fanData.fan_state === "on" ? "green" : "red";
        }

        const modeEl = document.getElementById("fan_mode");
        if (modeEl && overrideRes.ok) {
            const overrideData = await overrideRes.json();
            if (overrideData.active) {
                modeEl.textContent = "⚡ Override";
                modeEl.style.color = "orange";
            } else {
                modeEl.textContent = "🔄 Automatik";
                modeEl.style.color = "green";
            }
        }
    } catch (e) {
        // Verbindung fehlgeschlagen – still ignorieren
    }
}

// ---------------- FORECAST (Dashboard) ----------------
async function loadForecast() {
    const el = document.getElementById("forecast_content");
    if (!el) return;

    try {
        const res = await fetch("/api/forecast?tage=1", { credentials: "include" });
        const data = await res.json();

        if (data.error) {
            el.innerHTML = `<p>${data.error}</p>`;
            return;
        }

        const next = data.naechstes_lueftungsfenster;
        let html = `<p><b>${data.stadt}</b> – ${data.optimale_stunden_gesamt} optimale Stunden heute</p>`;

        if (next) {
            const zeit = new Date(next.zeit).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
            html += `<p>Nächstes Lüftungsfenster: <b>${zeit}</b> (${next.temperatur}°C, ${next.luftfeuchtigkeit}% Feuchte)</p>`;
        } else {
            html += `<p style="color: orange;">Aktuell kein optimales Lüftungsfenster</p>`;
        }

        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = "<p>Wetterdaten nicht verfügbar</p>";
    }
}

// ---------------- ENERGIE (Dashboard) ----------------
async function loadEnergieDashboard() {
    const el = document.getElementById("energie_content");
    if (!el) return;

    try {
        const res = await fetch("/api/energie", { credentials: "include" });
        const data = await res.json();

        if (data.error) {
            el.innerHTML = `<p>${data.error}</p>`;
            return;
        }

        el.innerHTML = `
            <div class="fan-grid">
                <div>Verbrauch<br><b>${data.verbrauch_kwh.gesamt} kWh</b></div>
                <div>Kosten<br><b>${data.kosten_eur.gesamt} €</b></div>
                <div>Lüfter-Anteil<br><b>${data.laufzeit.luefter_anteil_prozent}%</b></div>
            </div>`;
    } catch (e) {
        el.innerHTML = "<p>Nicht verfügbar</p>";
    }
}

// ---------------- HEALTH (Dashboard) ----------------
async function loadHealth() {
    const el = document.getElementById("health_content");
    if (!el) return;

    try {
        const res = await fetch("/api/health", { credentials: "include" });
        const data = await res.json();

        let statusColor = data.sensor_aktiv ? "green" : "red";
        let statusText = data.sensor_aktiv ? "✅ Online" : "❌ Offline";

        el.innerHTML = `
            <div class="fan-grid">
                <div>Sensor<br><b style="color: ${statusColor};">${statusText}</b></div>
                <div>Messungen heute<br><b>${data.messungen_heute || 0}</b></div>
                <div>DB<br><b style="color: ${data.db_connected ? 'green' : 'red'};">${data.db_connected ? '✅' : '❌'}</b></div>
            </div>
            ${data.warnung ? `<p style="color: orange; margin-top: 0.5rem;">⚠️ ${data.warnung}</p>` : ''}`;
    } catch (e) {
        el.innerHTML = "<p>Nicht verfügbar</p>";
    }
}

// ---------------- INIT ----------------
loadSensors();
loadFan();
loadForecast();
loadEnergieDashboard();
loadHealth();

setInterval(() => loadSensors(), 5000);
setInterval(loadFan, 2000);
