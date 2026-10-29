(function () {
  const fmtInt = n => Number(n).toLocaleString("es-PE");
  const fmtMoney = n => "S/ " + Number(n).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const REASONS = {
    SALIDA: ["Venta mostrador", "Venta obra", "Devolución a proveedor", "Consumo interno"],
    AJUSTE: ["Merma", "Producto dañado", "Diferencia de conteo", "Inventario inicial"],
  };
  const TYPE_TAG = {
    ENTRADA: '<span class="tag tag-green">Entrada</span>',
    SALIDA: '<span class="tag tag-red">Salida</span>',
    AJUSTE: '<span class="tag tag-gray">Ajuste</span>',
  };

  const els = {
    tabs: document.querySelectorAll("#type-tabs .tab"),
    form: document.getElementById("move-form"),
    product: document.getElementById("f-product"),
    productList: document.getElementById("product-list"),
    qty: document.getElementById("f-qty"),
    qtyLabel: document.getElementById("qty-label"),
    supplierField: document.getElementById("supplier-field"),
    supplier: document.getElementById("f-supplier"),
    reason: document.getElementById("f-reason"),
    reasonLabel: document.getElementById("reason-label"),
    reasonList: document.getElementById("reason-list"),
    submit: document.getElementById("btn-register"),
    message: document.getElementById("form-message"),
    kardexTitle: document.getElementById("kardex-title"),
    kardexWrap: document.getElementById("kardex-wrap"),
    exportBtn: document.getElementById("btn-export-kardex"),
  };

  let type = "ENTRADA";
  let products = [];
  let current = null;      // producto seleccionado
  let movements = [];

  const label = p => `${p.code} · ${p.name}`;

  function showMessage(text, kind) {
    els.message.innerHTML = text ? `<div class="flash flash-${kind}">${esc(text)}</div>` : "";
  }

  function setType(newType) {
    type = newType;
    els.tabs.forEach(t => t.classList.toggle("active", t.dataset.type === type));
    const isEntry = type === "ENTRADA";
    els.supplierField.style.visibility = isEntry ? "visible" : "hidden";
    els.reasonLabel.textContent = isEntry ? "Guía de remisión" : "Motivo";
    els.reason.required = type === "AJUSTE";
    els.reason.value = "";
    els.reason.placeholder = isEntry ? "Ej. T001-004512" : (type === "AJUSTE" ? "Obligatorio" : "Ej. Venta mostrador");
    els.reasonList.innerHTML = (REASONS[type] || []).map(r => `<option value="${esc(r)}">`).join("");
    els.qtyLabel.textContent = type === "AJUSTE" ? "Cantidad (+ suma / − resta)" : "Cantidad";
    els.qty.min = type === "AJUSTE" ? "" : "1";
    showMessage("", "");
    updatePreview();
  }

  function delta() {
    const q = parseInt(els.qty.value, 10);
    if (!Number.isFinite(q) || q === 0) return null;
    return type === "SALIDA" ? -Math.abs(q) : (type === "ENTRADA" ? Math.abs(q) : q);
  }

  function updateCards() {
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    if (!current) {
      ["st-current", "st-min", "st-after", "st-price"].forEach(id => set(id, "—"));
      ["st-unit", "st-alert", "st-after-sub", "st-cost"].forEach(id => set(id, " "));
      return;
    }
    set("st-current", fmtInt(current.stock));
    set("st-unit", current.unit);
    set("st-min", fmtInt(current.minStock));
    set("st-alert", current.openAlert ? "alerta activa" : "sin alerta");
    set("st-price", fmtMoney(current.salePrice));
    set("st-cost", "costo " + fmtMoney(current.cost));
    updatePreview();
  }

  function updatePreview() {
    const valueEl = document.getElementById("st-after");
    const subEl = document.getElementById("st-after-sub");
    valueEl.classList.remove("is-ok", "is-warn", "is-danger");
    const d = delta();
    if (!current || d === null) {
      valueEl.textContent = "—";
      subEl.textContent = " ";
      return;
    }
    const after = current.stock + d;
    valueEl.textContent = fmtInt(after);
    if (after < 0) {
      valueEl.classList.add("is-danger");
      subEl.textContent = "no hay stock suficiente";
    } else if (current.minStock > 0 && after <= current.minStock) {
      valueEl.classList.add("is-warn");
      subEl.textContent = "queda en o bajo el mínimo";
    } else {
      valueEl.classList.add("is-ok");
      subEl.textContent = "supera el mínimo";
    }
  }

  function renderKardex() {
    els.exportBtn.disabled = !movements.length;
    if (!current) { renderEmpty(els.kardexWrap, "Selecciona un producto para ver su kardex"); return; }
    els.kardexTitle.textContent = "Kardex · " + current.name;
    if (!movements.length) { renderEmpty(els.kardexWrap, "Este producto aún no tiene movimientos"); return; }
    els.kardexWrap.innerHTML = `<table><thead><tr>
        <th>Fecha</th><th>Tipo</th><th class="num">Cantidad</th><th class="num">Stock resultante</th>
        <th>Proveedor / motivo</th><th>Usuario</th>
      </tr></thead><tbody>${movements.map(m => `<tr>
        <td>${formatDateTime(m.createdAt)}</td>
        <td>${TYPE_TAG[m.type] || esc(m.type)}</td>
        <td class="num">${m.quantity > 0 ? "+" : "−"}${fmtInt(Math.abs(m.quantity))}</td>
        <td class="num">${fmtInt(m.resultingStock)}</td>
        <td>${esc(describe(m))}</td>
        <td>${esc(m.user)}</td></tr>`).join("")}</tbody></table>`;
  }

  function describe(m) {
    if (m.supplier && m.reason) return `${m.supplier} · ${m.reason}`;
    return m.supplier || m.reason || "";
  }

  function formatDateTime(iso) {
    const [d, t] = iso.split("T");
    return `${d.split("-").reverse().join("/")} ${t.slice(0, 5)}`;
  }

  async function loadKardex(productId) {
    const data = await fetchJSON(`/api/inventory/products/${productId}/kardex`);
    current = data.product;
    movements = data.movements;
    updateCards();
    renderKardex();
  }

  function selectFromInput() {
    const text = els.product.value.trim();
    const p = products.find(x => label(x) === text)
      || products.find(x => x.code.toLowerCase() === text.toLowerCase());
    if (!p) {
      current = null;
      movements = [];
      els.kardexTitle.textContent = "Kardex";
      updateCards();
      renderKardex();
      return;
    }
    els.product.value = label(p);
    loadKardex(p.id).catch(err => showMessage(err.message, "error"));
  }

  async function loadProducts() {
    products = await fetchJSON("/api/inventory/products");
    els.productList.innerHTML = products.map(p => `<option value="${esc(label(p))}">`).join("");
    if (!products.length) {
      showMessage("Aún no hay productos registrados. Ejecuta seed_inventory.py para cargar datos de ejemplo.", "error");
    }
  }

  async function submit(e) {
    e.preventDefault();
    if (!current) { showMessage("Elige un producto de la lista.", "error"); return; }
    const d = delta();
    if (d === null) { showMessage("Ingresa una cantidad distinta de cero.", "error"); return; }
    els.submit.disabled = true;
    try {
      const res = await fetch("/api/inventory/movements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productId: current.id,
          type,
          quantity: type === "AJUSTE" ? d : Math.abs(d),
          supplierId: type === "ENTRADA" ? (els.supplier.value || null) : null,
          reason: els.reason.value,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `Error ${res.status}`);
      const p = products.find(x => x.id === current.id);
      if (p) p.stock = body.product.stock;
      let msg = `${type === "ENTRADA" ? "Entrada" : type === "SALIDA" ? "Salida" : "Ajuste"} registrada. Stock actual: ${fmtInt(body.product.stock)}.`;
      if (body.alertOpened) msg += " Se generó una alerta de stock mínimo.";
      showMessage(msg, "success");
      els.qty.value = "";
      els.reason.value = "";
      await loadKardex(current.id);
    } catch (err) {
      showMessage(err.message, "error");
    } finally {
      els.submit.disabled = false;
    }
  }

  els.tabs.forEach(t => t.addEventListener("click", () => setType(t.dataset.type)));
  els.product.addEventListener("change", selectFromInput);
  els.qty.addEventListener("input", updatePreview);
  els.form.addEventListener("submit", submit);
  els.exportBtn.addEventListener("click", () => {
    if (!current) return;
    const ws = XLSX.utils.json_to_sheet(movements.map(m => ({
      "Fecha": formatDateTime(m.createdAt), "Tipo": m.type, "Cantidad": m.quantity,
      "Stock resultante": m.resultingStock, "Proveedor / motivo": describe(m), "Usuario": m.user,
    })));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Kardex");
    XLSX.writeFile(wb, `kardex_${current.code}_${localDateISO()}.xlsx`);
  });

  setType("ENTRADA");
  Promise.all([
    loadProducts(),
    fetchJSON("/api/inventory/suppliers").then(rows => {
      els.supplier.insertAdjacentHTML("beforeend",
        rows.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join(""));
    }),
  ]).then(() => {
    const code = new URLSearchParams(location.search).get("code");
    if (code) {
      els.product.value = code;
      selectFromInput();
    }
  }).catch(err => showMessage(err.message, "error"));
})();
