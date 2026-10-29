/**
 * Gráficos de la landing page. Los datos son sintéticos / ilustrativos —
 * sirven para mostrar cómo se ve el producto, no son precios reales de
 * ninguna tienda.
 */
(function () {
  const RETAIL_COLORS = {
    FALABELLA: "#22c55e",
    SODIMAC: "#e11d48",
    PROMART: "#f97316",
    PLAZAVEA: "#eab308",
    TOTTUS: "#0ea5e9",
  };

  function dateLabel(d) {
    return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function buildSeries(retailDefs, days) {
    const today = new Date();
    const labels = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      labels.push(dateLabel(d));
    }
    const datasets = retailDefs.map((def, idx) => {
      let price = def.base;
      const data = labels.map((_, i) => {
        price += (Math.sin(i / 3.2 + idx) * def.vol * 0.5) + (Math.random() - 0.5) * def.vol * 0.6;
        price = Math.max(def.base - def.vol * 2, Math.min(def.base + def.vol * 2, price));
        return Math.round(price);
      });
      return {
        label: def.label,
        data,
        borderColor: def.color,
        backgroundColor: def.color,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.25,
      };
    });
    return { labels, datasets };
  }

  function buildChart(canvasId, { days, compact }) {
    const el = document.getElementById(canvasId);
    if (!el) return;

    const retailDefs = [
      { label: "FALABELLA", base: 1638, vol: 60, color: RETAIL_COLORS.FALABELLA },
      { label: "SODIMAC", base: 1810, vol: 70, color: RETAIL_COLORS.SODIMAC },
      { label: "PROMART", base: 1768, vol: 55, color: RETAIL_COLORS.PROMART },
    ];
    const { labels, datasets } = buildSeries(retailDefs, days);

    new Chart(el, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: !compact,
            position: "bottom",
            labels: { boxWidth: 10, font: { size: 11 }, color: "#545B6E" },
          },
          tooltip: {
            backgroundColor: "#10182B",
            titleColor: "#fff",
            bodyColor: "#e5e7eb",
            padding: 10,
            cornerRadius: 8,
            callbacks: {
              label: (c) => ` ${c.dataset.label}: S/ ${c.formattedValue}`,
            },
          },
        },
        scales: {
          x: {
            display: !compact,
            grid: { display: false },
            ticks: { color: "#8a90a6", maxTicksLimit: 8, font: { size: 10 } },
          },
          y: {
            display: !compact,
            beginAtZero: false,
            grid: { color: "rgba(16,24,43,0.05)" },
            ticks: { color: "#8a90a6", font: { size: 10 }, callback: (v) => "S/" + v },
          },
        },
      },
    });
  }

  window.addEventListener("load", () => {
    buildChart("heroChart", { days: 14, compact: true });
    buildChart("demoChart", { days: 30, compact: false });
  });
})();
