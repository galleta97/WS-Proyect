(function () {
  const tableWrap = document.getElementById("table-wrap");

  async function load() {
    const { data } = await fetchJSON("/api/alerts?page=1&size=50");
    if (!data.length) {
      renderEmpty(tableWrap, "No hay alertas todavía");
      return;
    }
    renderTable(tableWrap, [
      { key: "createdAt", label: "Fecha", render: r => r.createdAt.replace("T", " ").slice(0, 19) },
      { key: "productCode", label: "Producto" },
      { key: "retail", label: "Tienda" },
      { key: "alertType", label: "Tipo", render: r => r.alertType === "stock_change" ? "Stock" : "Precio" },
      { key: "previousValue", label: "Antes" },
      { key: "newValue", label: "Ahora" },
      { key: "notified", label: "Notificado", render: r => r.notified ? "✅" : "⚠️ " + (r.notifyError || "no enviado") },
    ], data);
  }

  document.getElementById("btn-refresh").addEventListener("click", load);
  load();
})();
