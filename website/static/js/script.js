
async function loadWeather() {
    const res = await fetch("/api/weather", { credentials: "include" });
    const data = await res.json();

    document.getElementById("weather_temp").textContent = data.temperature;
    document.getElementById("weather_wind").textContent = data.windspeed;
    document.getElementById("weather_time").textContent = data.time;
}

async function loadSensors() {
    const res = await fetch("/api/sensoren", { credentials: "include" });
    const data = await res.json();

    const tbody = document.getElementById("sensor_table_body");
    tbody.innerHTML = "";

    data.forEach(r => {
        tbody.innerHTML += `
        <tr>
            <td>${r.timestamp}</td>
            <td>${r.temp_innen} °C</td>
            <td>${r.temp_aussen} °C</td>
            <td>${r.hum_innen} %</td>
            <td>${r.hum_aussen} %</td>
        </tr>`;
    });
}

async function loadFan() {
    const res = await fetch("/api/fan", { credentials: "include" });
    const data = await res.json();

    document.getElementById("fan_state").textContent = data.state;
    document.getElementById("fan_mode").textContent = data.mode;
    document.getElementById("fan_speed").textContent = data.speed;
}

async function loadWeather() {
    const res = await fetch("/api/weather", { credentials: "include" });
    const data = await res.json();

    document.getElementById("weather_temp").textContent = data.temperature;
    document.getElementById("weather_wind").textContent = data.windspeed;
    document.getElementById("weather_time").textContent = data.time;
}


setInterval(() => {
    const g = document.getElementById("gauge_number");
    if (g) g.textContent = Math.floor(Math.random() * 100) + "%";
}, 2000);

loadWeather();
loadSensors();
loadFan();

setInterval(loadWeather, 60000);
setInterval(loadSensors, 5000);
setInterval(loadFan, 3000);