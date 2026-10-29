"""
Lógica de negocio del módulo de inventario (FerreControl).

- register_movement(): registra una entrada, salida o ajuste en una sola
  transacción, actualiza el stock, escribe el kardex y abre o cierra la
  alerta de stock mínimo (CU04 y CU11 del informe).
- dashboard_summary(): calcula los indicadores y listas del dashboard.
"""

from datetime import datetime, timedelta

from sqlalchemy import func

from extensions import db
from models import (
    MOVEMENT_TYPES,
    PriceEntry,
    Product,
    Retail,
    StockAlert,
    StockMovement,
    Supplier,
)

# Un producto en o bajo su mínimo es CRÍTICO si le queda el 30 % o menos
# del stock mínimo; si no, está BAJO.
CRITICAL_RATIO = 0.30
# Ventana para la rotación y para considerar "vigente" un precio capturado.
ROTATION_DAYS = 30
PRICE_WINDOW_DAYS = 30


class InventoryError(ValueError):
    """Error de validación que se muestra tal cual al usuario."""


def register_movement(product_id, movement_type, quantity, user_id,
                      supplier_id=None, reason=None, when=None, commit=True):
    """Registra un movimiento y devuelve (movimiento, alerta_abierta_o_None).

    `quantity` llega como la escribe el usuario: positiva para entradas y
    salidas; en los ajustes puede ser positiva o negativa.
    """
    movement_type = (movement_type or "").upper().strip()
    if movement_type not in MOVEMENT_TYPES:
        raise InventoryError("Tipo de movimiento no válido.")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise InventoryError("La cantidad debe ser un número entero.")
    if quantity == 0:
        raise InventoryError("La cantidad no puede ser cero.")
    if movement_type in ("ENTRADA", "SALIDA") and quantity < 0:
        raise InventoryError("En entradas y salidas la cantidad debe ser positiva.")
    reason = (reason or "").strip() or None
    if movement_type == "AJUSTE" and not reason:
        raise InventoryError("Indica el motivo del ajuste.")

    product = db.session.get(Product, int(product_id)) if product_id else None
    if product is None or not product.active:
        raise InventoryError("El producto no existe o está inactivo.")

    supplier = None
    if movement_type == "ENTRADA" and supplier_id:
        supplier = db.session.get(Supplier, int(supplier_id))
        if supplier is None:
            raise InventoryError("El proveedor no existe.")

    delta = -quantity if movement_type == "SALIDA" else quantity
    new_stock = product.stock + delta
    if new_stock < 0:
        raise InventoryError(
            f"Stock insuficiente: el stock disponible es {product.stock}.")

    product.stock = new_stock
    movement = StockMovement(
        product_id=product.id,
        user_id=user_id,
        supplier_id=supplier.id if supplier else None,
        type=movement_type,
        quantity=delta,
        resulting_stock=new_stock,
        reason=reason,
        created_at=when or datetime.now(),
    )
    db.session.add(movement)

    opened = _sync_stock_alert(product, when or datetime.now())
    if commit:
        db.session.commit()
    return movement, opened


def _sync_stock_alert(product, when):
    """Abre una alerta si el stock llegó al mínimo (y no había una abierta);
    cierra las abiertas si el stock ya lo supera."""
    open_alert = StockAlert.query.filter_by(product_id=product.id, status="ABIERTA").first()
    below = product.min_stock > 0 and product.stock <= product.min_stock
    if below and open_alert is None:
        alert = StockAlert(
            product_id=product.id,
            message=f"Stock {product.stock} ≤ mínimo {product.min_stock}",
            created_at=when,
        )
        db.session.add(alert)
        return alert
    if not below and open_alert is not None:
        open_alert.status = "CERRADA"
        open_alert.closed_at = when
    return None


def stock_status(product):
    """CRÍTICO / BAJO / OK según el stock frente al mínimo."""
    if product.min_stock <= 0 or product.stock > product.min_stock:
        return "OK"
    if product.stock <= product.min_stock * CRITICAL_RATIO:
        return "CRITICO"
    return "BAJO"


def latest_competitor_prices(price_codes, exclude_retail_code=None):
    """Último precio de cada competidor para cada price_code.

    Misma regla que la matriz de precios: por tienda se toma la fecha más
    reciente y, entre varios listados de ese día, el más barato con stock.
    Devuelve {price_code: {retail_code: {"price", "date", "inStock"}}}.
    """
    if not price_codes:
        return {}
    codes = list(price_codes)
    # La ventana se cuenta desde la última captura disponible (no desde hoy):
    # si la captura se detiene unos días, el dashboard sigue mostrando los
    # últimos precios conocidos en vez de quedar vacío.
    newest = (db.session.query(func.max(PriceEntry.date))
              .filter(PriceEntry.product_code.in_(codes)).scalar())
    if newest is None:
        return {}
    since = newest - timedelta(days=PRICE_WINDOW_DAYS)
    q = (db.session.query(PriceEntry, Retail.code)
         .join(Retail, Retail.id == PriceEntry.retail_id)
         .filter(PriceEntry.product_code.in_(codes))
         .filter(PriceEntry.date >= since))
    if exclude_retail_code:
        q = q.filter(Retail.code != exclude_retail_code)

    by_pair = {}
    for entry, retail_code in q.all():
        by_pair.setdefault((entry.product_code, retail_code), []).append(entry)

    result = {}
    for (code, retail_code), rows in by_pair.items():
        last_date = max(r.date for r in rows)
        rows = [r for r in rows if r.date == last_date]
        in_stock = [r for r in rows if r.is_available is not False and float(r.min_price) > 0]
        best = min(in_stock or rows, key=lambda r: float(r.min_price))
        result.setdefault(code, {})[retail_code] = {
            "price": float(best.min_price),
            "date": last_date,
            "inStock": bool(in_stock),
        }
    return result


def dashboard_summary(reference_retail_code=None):
    """Indicadores del dashboard (RF17)."""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    products = Product.query.filter_by(active=True).all()

    low = [p for p in products if stock_status(p) != "OK"]
    low.sort(key=lambda p: (p.stock / p.min_stock if p.min_stock else 1, p.code))

    today_moves = (db.session.query(StockMovement.type, func.count(StockMovement.id))
                   .filter(StockMovement.created_at >= today)
                   .group_by(StockMovement.type).all())
    moves_by_type = {t: n for t, n in today_moves}

    since = now - timedelta(days=ROTATION_DAYS)
    rotation_rows = (db.session.query(Product, func.sum(-StockMovement.quantity).label("units"))
                     .join(StockMovement, StockMovement.product_id == Product.id)
                     .filter(StockMovement.type == "SALIDA", StockMovement.created_at >= since)
                     .group_by(Product.id)
                     .order_by(func.sum(-StockMovement.quantity).desc())
                     .limit(6).all())

    linked = [p for p in products if p.price_code]
    competitor = latest_competitor_prices({p.price_code for p in linked}, reference_retail_code)
    comparisons, last_capture = [], None
    for p in linked:
        prices = {rc: v for rc, v in competitor.get(p.price_code, {}).items() if v["inStock"]}
        if not prices:
            continue
        retail_code, best = min(prices.items(), key=lambda kv: kv[1]["price"])
        own = float(p.sale_price)
        diff = (own - best["price"]) / best["price"] * 100 if best["price"] else 0.0
        position = "mas_caro" if diff > 0.05 else ("mas_barato" if diff < -0.05 else "igual_mercado")
        newest = max(v["date"] for v in prices.values())
        last_capture = newest if last_capture is None or newest > last_capture else last_capture
        comparisons.append({
            "code": p.code,
            "name": p.name,
            "ownPrice": own,
            "competitorPrice": best["price"],
            "retail": retail_code,
            "diffPct": round(diff, 1),
            "position": position,
            "competitors": len(prices),
        })
    comparisons.sort(key=lambda c: c["diffPct"], reverse=True)

    return {
        "kpis": {
            "activeProducts": len(products),
            "categories": len({p.category_id for p in products}),
            "belowMin": len(low),
            "moreExpensive": sum(1 for c in comparisons if c["position"] == "mas_caro"),
            "compared": len(comparisons),
            "movementsToday": sum(moves_by_type.values()),
            "entriesToday": moves_by_type.get("ENTRADA", 0),
            "exitsToday": moves_by_type.get("SALIDA", 0),
            "adjustmentsToday": moves_by_type.get("AJUSTE", 0),
        },
        "lowStock": [{
            "code": p.code, "name": p.name, "stock": p.stock,
            "minStock": p.min_stock, "unit": p.unit, "status": stock_status(p),
        } for p in low[:10]],
        "rotation": [{"code": p.code, "name": p.name, "units": int(units)} for p, units in rotation_rows],
        "comparisons": comparisons[:10],
        "lastCapture": last_capture.isoformat() if last_capture else None,
        "referenceRetail": reference_retail_code,
    }
