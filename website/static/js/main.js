// demo
setInterval(() => {
    const gauge = document.getElementById("gauge_number");
    if (gauge) {
        gauge.textContent = Math.floor(Math.random() * 101) + "%";
    }
}, 1500);
