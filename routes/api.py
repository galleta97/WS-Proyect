"""
Endpoints JSON del dashboard.

La forma de cada ruta (query params, paginación, estructura de respuesta)
sigue el mismo patrón que mapeamos de la plataforma de referencia: filtros
por categoryIds[]/retailIds[]/brandIds[], paginación con page/size, y un
endpoint de "price matrix" compartido para la vista de ranking de ventas
("Top Sales"), activado con hasSalesRank=true.
"""

from datetime import date, datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from extensions import db
from models import (
    Brand,
    Category,
    Feature,
    ImportRecord,
    Importer,
    MktEvent,
    PriceAlert,
    PriceEntry,
    Retail,
    WebHome,
    WebHomePrice,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Tienda de referencia para el badge de posición de precio (Fase 2).
# Decisión: cuenta TODO lo que se publica en esa tienda, sin importar quién
# lo vende (en promart.pe hay productos de terceros; el cliente los ve y los
# compara igual). El vendedor se guarda siempre (campo `seller`) para poder
# filtrar "solo lo que vende la propia tienda" cuando haga falta.
# Cámbialo aquí si en el futuro necesitas otra tienda de referencia, o
# vuélvelo configurable por cliente cuando llegue la arquitectura
# multi-tenant (Fase 7).
REFERENCE_RETAIL_CODE = "PROMART"

# URL publica del producto en cada tienda. Se construye desde `listing_ref`
# (el productId que trae la captura), asi el precio de cada fila se puede
# abrir en la pagina real y contrastar el dato scrapeado contra la pagina.
# Promart/Metro/Oechsle/Carsa son VTEX y SOLO resuelven con el slug completo
# (terminado en /p); el productId a secas cae en el buscador (buscavazia).
# Sodimac es Next.js y usa /sodimac-pe/articulo/<productId>.
STORE_URL_PATTERNS = {
    "PROMART": "https://www.promart.pe/{ref}",
    "METRO": "https://www.metro.pe/{ref}",
    "OECHSLE": "https://www.oechsle.pe/{ref}",
    "CARSA": "https://www.carsa.pe/{ref}",
    "SODIMAC": "https://www.sodimac.com.pe/sodimac-pe/articulo/{ref}",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store_url(retail_code, listing_ref, saved_url=None):
    """URL publica del producto en la tienda, o None si no se puede construir.

    Prioridad: la URL real guardada en la captura (trae el slug tal como la
    publica la tienda; es el unico formato que resuelven las tiendas VTEX:
    Promart, Metro, Oechsle y Carsa). El patron por productId solo es
    confiable para Sodimac.
    """
    if saved_url and str(saved_url).strip():
        return str(saved_url).strip()
    pattern = STORE_URL_PATTERNS.get((retail_code or "").strip().upper())
    ref = str(listing_ref or "").strip()
    if not pattern or not ref.isdigit():
        return None
    return pattern.format(ref=ref)


def _int_list(param_name):
    """Lee querystring tipo ?categoryIds[]=1&categoryIds[]=2 -> [1, 2]."""
    values = request.args.getlist(f"{param_name}[]") or request.args.getlist(param_name)
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _parse_date(param_name, default=None):
    raw = request.args.get(param_name)
    if not raw:
        return default
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return default


def _paginate(query, default_size=50):
    page = max(1, request.args.get("page", 1, type=int))
    size = max(1, min(200, request.args.get("size", default_size, type=int)))
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return items, {
        "total": total,
        "page": page,
        "size": size,
        "totalPages": (total + size - 1) // size if size else 0,
    }


# ---------------------------------------------------------------------------
# Catálogos compartidos
# ---------------------------------------------------------------------------

@api_bp.route("/categories/")
def categories():
    return jsonify([c.to_dict() for c in Category.query.order_by(Category.code).all()])


@api_bp.route("/retails/")
def retails():
    return jsonify([r.to_dict() for r in Retail.query.order_by(Retail.code).all()])


@api_bp.route("/brands/")
def brands():
    category_ids = _int_list("categoryIds")
    q = Brand.query
    if category_ids:
        q = q.join(Brand.category_ids).filter(Category.id.in_(category_ids))
    return jsonify([b.to_dict() for b in q.order_by(Brand.code).all()])


@api_bp.route("/features/")
def features():
    category_ids = _int_list("categoryIds")
    q = Feature.query
    if category_ids:
        q = q.filter(Feature.category_id.in_(category_ids))
    return jsonify([f.to_dict() for f in q.order_by(Feature.code).all()])


@api_bp.route("/mkt-event/")
def mkt_events():
    return jsonify([e.to_dict() for e in MktEvent.query.order_by(MktEvent.from_date.desc()).all()])


@api_bp.route("/products")
def products_catalog():
    """Códigos de producto distintos disponibles en PriceEntry, para el
    filtro 'Products' de la búsqueda de precios."""
    category_ids = _int_list("categoryIds")
    q = db.session.query(PriceEntry.product_code).distinct()
    if category_ids:
        q = q.filter(PriceEntry.category_id.in_(category_ids))
    codes = [c[0] for c in q.order_by(PriceEntry.product_code).all()]
    return jsonify([{"id": c, "code": c} for c in codes])


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

@api_bp.route("/categories/imports")
def categories_imports():
    """Solo categorías que efectivamente tienen registros de importación."""
    rows = (
        db.session.query(Category)
        .join(ImportRecord, ImportRecord.category_id == Category.id)
        .distinct()
        .order_by(Category.code)
        .all()
    )
    return jsonify([c.to_dict() for c in rows])


@api_bp.route("/retails/imports")
def retails_imports():
    # En 3Eye este endpoint devuelve el set de retailers relevante para
    # importaciones; aquí devolvemos todos por simplicidad.
    return jsonify([r.to_dict() for r in Retail.query.order_by(Retail.code).all()])


@api_bp.route("/imports/brands")
def imports_brands():
    category_ids = _int_list("categoryIds")
    q = (
        db.session.query(Brand)
        .join(ImportRecord, ImportRecord.brand_id == Brand.id)
    )
    if category_ids:
        q = q.filter(ImportRecord.category_id.in_(category_ids))
    return jsonify([b.to_dict() for b in q.distinct().order_by(Brand.code).all()])


@api_bp.route("/imports/importers")
def imports_importers():
    category_ids = _int_list("categoryIds")
    q = (
        db.session.query(Importer)
        .join(ImportRecord, ImportRecord.importer_id == Importer.id)
    )
    if category_ids:
        q = q.filter(ImportRecord.category_id.in_(category_ids))
    return jsonify([i.to_dict() for i in q.distinct().order_by(Importer.code).all()])


@api_bp.route("/imports/products")
def imports_products():
    category_ids = _int_list("categoryIds")
    q = db.session.query(ImportRecord.product_code, ImportRecord.brand_id).distinct()
    if category_ids:
        q = q.filter(ImportRecord.category_id.in_(category_ids))
    return jsonify(
        [{"code": code, "brandIds": brand_id} for code, brand_id in q.limit(500).all()]
    )


@api_bp.route("/imports/")
def imports_list():
    category_ids = _int_list("categoryIds")
    brand_ids = _int_list("brandIds")
    importer_ids = _int_list("importerIds")
    retail_ids = _int_list("retailIds")  # no aplica directo a esta tabla, se ignora si no matchea
    from_date = _parse_date("fromDate")
    to_date = _parse_date("toDate")

    q = ImportRecord.query
    if category_ids:
        q = q.filter(ImportRecord.category_id.in_(category_ids))
    if brand_ids:
        q = q.filter(ImportRecord.brand_id.in_(brand_ids))
    if importer_ids:
        q = q.filter(ImportRecord.importer_id.in_(importer_ids))
    if from_date:
        q = q.filter(ImportRecord.date >= from_date)
    if to_date:
        q = q.filter(ImportRecord.date <= to_date)

    q = q.order_by(ImportRecord.date.desc())
    items, meta = _paginate(q)
    return jsonify({"data": [i.to_dict() for i in items], "meta": meta})


# ---------------------------------------------------------------------------
# Web Homes
# ---------------------------------------------------------------------------

@api_bp.route("/web-home/homes")
def web_home_homes():
    return jsonify([h.to_dict() for h in WebHome.query.order_by(WebHome.retail_id).all()])


@api_bp.route("/web-home/brands")
def web_home_brands():
    q = (
        db.session.query(Brand)
        .join(WebHomePrice, WebHomePrice.brand_id == Brand.id)
        .distinct()
        .order_by(Brand.code)
    )
    return jsonify([b.to_dict() for b in q.all()])


@api_bp.route("/web-home/image-alts")
def web_home_image_alts():
    # Placeholder: en 3Eye esto filtra por tipo de imagen detectada
    # (banner, ficha de producto, etc.). Devolvemos un catálogo fijo simple.
    return jsonify([
        {"id": 1, "code": "BANNER"},
        {"id": 2, "code": "PRODUCT_CARD"},
    ])


@api_bp.route("/web-home/prices")
def web_home_prices():
    retail_ids = _int_list("retailIds")
    brand_ids = _int_list("brandIds")
    from_date = _parse_date("fromDate")
    to_date = _parse_date("toDate")

    q = WebHomePrice.query
    if retail_ids:
        q = q.filter(WebHomePrice.retail_id.in_(retail_ids))
    if brand_ids:
        q = q.filter(WebHomePrice.brand_id.in_(brand_ids))
    if from_date:
        q = q.filter(WebHomePrice.date >= from_date)
    if to_date:
        q = q.filter(WebHomePrice.date <= to_date)

    q = q.order_by(WebHomePrice.date.desc())
    items, meta = _paginate(q, default_size=20)
    return jsonify({"data": [p.to_dict() for p in items], "meta": meta})


# ---------------------------------------------------------------------------
# Price matrix (Search normal + Top Sales)
# ---------------------------------------------------------------------------

@api_bp.route("/prices/matrix")
def prices_matrix():
    """
    Search / "Modes" (hasSalesRank ausente/false): compara precios de un
    mismo producto entre tiendas -> 1 fila = 1 SKU único (match exacto por
    product_code + brand_id, nunca combinando productos distintos), usando
    SIEMPRE el precio del scrape más reciente disponible por tienda —
    vacío si esa tienda no tiene ningún registro de ese SKU. No exige que
    todas las tiendas compartan la misma fecha exacta de scrape: cada
    columna muestra su propio dato más actual, que es lo que realmente
    significa "datos actuales" en una comparación entre tiendas que se
    scrapean en momentos distintos.

    Top Sales (hasSalesRank=true): devuelve el ranking de ventas para un
    rango de fechas/evento específico, ordenado por sales_rank — aquí sí
    aplica un filtro de fecha explícito porque el ranking es por período.
    """
    category_id = request.args.get("categoryId", type=int)
    category_ids = _int_list("categoryIds") or ([category_id] if category_id else [])
    retail_ids = _int_list("retailIds")
    brand_ids = _int_list("brandIds")
    feature_ids = _int_list("featureIds")
    product_codes = request.args.getlist("products[]") or request.args.getlist("products")
    has_sales_rank = request.args.get("hasSalesRank", "false").lower() == "true"

    q = PriceEntry.query
    if category_ids:
        q = q.filter(PriceEntry.category_id.in_(category_ids))
    if retail_ids:
        q = q.filter(PriceEntry.retail_id.in_(retail_ids))
    if brand_ids:
        q = q.filter(PriceEntry.brand_id.in_(brand_ids))
    if product_codes:
        q = q.filter(PriceEntry.product_code.in_(product_codes))
    # Nota: feature_ids no filtra PriceEntry todavía porque el modelo no
    # guarda la feature del producto en esta tabla; se deja el parámetro
    # aceptado para no romper el frontend, pendiente de modelar la relación
    # producto-feature cuando conectes datos reales.

    if has_sales_rank:
        from_date = _parse_date("fromDate")
        to_date = _parse_date("toDate")
        if from_date:
            q = q.filter(PriceEntry.date >= from_date)
        if to_date:
            q = q.filter(PriceEntry.date <= to_date)
        q = q.filter(PriceEntry.has_sales_rank.is_(True)).order_by(PriceEntry.sales_rank.asc())
        return jsonify([p.to_dict() for p in q.limit(200).all()])

    # --- Modo Search / "Modes": siempre el precio más reciente por tienda ---
    # Ordenamos por fecha descendente y nos quedamos con la PRIMERA fila que
    # veamos para cada (product_code, retail_id) = la más reciente de esa
    # tienda para ese SKU exacto. Esto es lo que corrige el bug reportado:
    # antes, si Falabella scrapeó el lunes y Sodimac el martes, comparar en
    # una fecha exacta dejaba una de las dos columnas vacía aunque sí
    # tuviera un precio reciente.
    # id desempata varias corridas el mismo día (mayor id = captura más reciente)
    rows_desc = q.order_by(PriceEntry.date.desc(), PriceEntry.id.desc()).all()
    seen, latest = set(), []
    for row in rows_desc:
        # listing_ref distingue varios listados del mismo modelo en una tienda
        # (marketplace); en datos sin listing_ref queda None y todo sigue igual.
        key = (row.product_code, row.retail_id, row.listing_ref)
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)

    # Varios listados del mismo modelo en una tienda: lo que muestra la web como
    # precio de ese modelo es el mas barato que se puede comprar. Si ninguno
    # tiene stock, se muestra el mas barato marcado como sin stock.
    # Solo se consideran los listados de la fecha mas reciente que tenga esa
    # tienda para ese SKU: listados de dias anteriores pueden referirse a
    # fragments que ya no estan publicados (y aun tener una URL vacia), y
    # mezclarlos hacia abajo el precio mostrado.
    by_pair = {}
    for row in latest:
        by_pair.setdefault((row.product_code, row.retail_id), []).append(row)
    rows, listing_counts = [], {}
    for pair, cands in by_pair.items():
        max_date = max(c.date for c in cands)
        cands = [c for c in cands if c.date == max_date]
        in_stock = [r for r in cands if r.is_available is not False and float(r.min_price) > 0]
        best = min(in_stock or cands, key=lambda r: float(r.min_price))
        rows.append(best)
        listing_counts[pair] = len(cands)
    rows.sort(key=lambda r: r.product_code)

    grouped = {}
    for row in rows:
        # Match exacto: product_code + brand_id. Nunca se combinan aquí
        # productos distintos aunque compartan nombre o marca parcial —
        # cada SKU único vive en su propia fila.
        key = (row.product_code, row.brand_id)
        grouped.setdefault(key, {
            "product": row.product_code,
            "brand": row.brand.code if row.brand else None,
            "category": row.category.code if row.category else None,
            "prices": {},
            "priceDates": {},
            "stock": {},
            "sellers": {},
            "listPrices": {},
            "cardPrices": {},
            "listings": {},
            "urls": {},
            "name": None,
        })
        retail_code = row.retail.code if row.retail else str(row.retail_id)
        # Ya viene deduplicado a 1 fila por (SKU, tienda) = la más reciente,
        # así que aquí no hace falta comparar mínimos entre fechas.
        grouped[key]["prices"][retail_code] = float(row.min_price)
        grouped[key]["priceDates"][retail_code] = row.date.isoformat()
        # Fase 4: disponibilidad de stock más reciente por tienda. None si
        # esa fuente todavía no reporta ese dato (no se asume "agotado").
        grouped[key]["stock"][retail_code] = row.is_available
        # Quién vende ese producto dentro de la tienda (None si no se informa).
        grouped[key]["sellers"][retail_code] = row.seller
        # Lo que muestra la web de ese listado: precio de lista y cuantos listados
        # del mismo modelo hay en esa tienda (de ahi sale el mas barato con stock).
        grouped[key]["listPrices"][retail_code] = float(row.list_price) if row.list_price else None
        grouped[key]["cardPrices"][retail_code] = float(row.card_price) if row.card_price else None
        grouped[key]["listings"][retail_code] = listing_counts.get((row.product_code, row.retail_id), 1)
        # URL del producto en esa tienda, para abrir la pagina y verificar
        # que el precio scrapeado sea el mismo que muestra el sitio.
        grouped[key]["urls"][retail_code] = _store_url(retail_code, row.listing_ref, row.url)
        if not grouped[key]["name"] and row.name:
            grouped[key]["name"] = row.name

    # --- Fase 2: posición de precio de la tienda de referencia ---
    # Por cada fila, calculamos precio_min/precio_max del mercado, y si
    # nuestra tienda de referencia (PROMART) está más barata, más cara, o
    # en línea con el mercado. Si la referencia no tiene precio para ese
    # SKU, la posición queda en null (no se puede comparar).
    #
    # Fase 4: las tiendas marcadas como agotadas (stock=False) NO cuentan
    # para el mínimo/máximo ni para la posición de referencia — no tiene
    # sentido decir que una tienda "tiene el mejor precio" de un producto
    # que ni siquiera puedes comprar ahí ahora mismo. Su precio se sigue
    # mostrando en la tabla (con el badge "Sin stock"), solo no participa
    # en la comparación.
    for entry in grouped.values():
        in_stock_prices = {
            rc: p for rc, p in entry["prices"].items()
            if entry["stock"].get(rc) is not False
        }
        if not in_stock_prices:
            entry["priceMin"] = None
            entry["priceMax"] = None
            entry["refStore"] = REFERENCE_RETAIL_CODE
            entry["refPosition"] = None
            continue

        price_min = min(in_stock_prices.values())
        price_max = max(in_stock_prices.values())
        entry["priceMin"] = price_min
        entry["priceMax"] = price_max
        entry["refStore"] = REFERENCE_RETAIL_CODE

        ref_price = in_stock_prices.get(REFERENCE_RETAIL_CODE)
        if ref_price is None:
            # O no hay precio de la referencia, o está agotada ahí — en
            # ambos casos no hay una comparación válida que mostrar.
            entry["refPosition"] = None
        elif len(in_stock_prices) < 2:
            # Solo hay un precio en el mercado: no hay con quien comparar, no se muestra etiqueta.
            entry["refPosition"] = None
        elif price_min == price_max:
            entry["refPosition"] = "igual_mercado"
        elif ref_price <= price_min:
            entry["refPosition"] = "mas_barato"
        elif ref_price >= price_max:
            entry["refPosition"] = "mas_caro"
        else:
            entry["refPosition"] = "igual_mercado"

    return jsonify(list(grouped.values()))


@api_bp.route("/prices/history")
def prices_history():
    """
    Serie histórica de precios para el generador de gráficos ("Price
    Tracking", "Retails by product", "Products by Retail") — alimenta las
    gráficas cuando el usuario selecciona uno o más productos en la tabla
    de Search.
    """
    products = request.args.getlist("products[]") or request.args.getlist("products")
    from_date = _parse_date("fromDate")
    to_date = _parse_date("toDate")

    if not products:
        return jsonify([])

    q = PriceEntry.query.filter(PriceEntry.product_code.in_(products))
    if from_date:
        q = q.filter(PriceEntry.date >= from_date)
    if to_date:
        q = q.filter(PriceEntry.date <= to_date)

    rows = q.order_by(PriceEntry.date.asc(), PriceEntry.id.asc()).all()
    # Un punto por (dia, modelo, tienda): con varios listados del mismo modelo,
    # el mas barato con stock ese dia (igual regla que la tabla de precios).
    per_day = {}
    for r in rows:
        per_day.setdefault((r.date, r.product_code, r.retail_id), []).append(r)
    points = []
    for (day, product, _retail_id), cands in per_day.items():
        in_stock = [c for c in cands if c.is_available is not False and float(c.min_price) > 0]
        best = min(in_stock or cands, key=lambda c: float(c.min_price))
        points.append({
            "date": day.isoformat(),
            "product": product,
            "retail": best.retail.code if best.retail else None,
            "price": float(best.min_price),
        })
    points.sort(key=lambda p: (p["date"], p["product"], p["retail"] or ""))
    return jsonify(points)


# ---------------------------------------------------------------------------
# Alertas (Fase 3 / Fase 4)
# ---------------------------------------------------------------------------

@api_bp.route("/alerts")
def alerts_list():
    """Últimas alertas de cambio de precio/stock, más recientes primero."""
    q = PriceAlert.query.order_by(PriceAlert.created_at.desc())
    items, meta = _paginate(q, default_size=50)
    return jsonify({"data": [a.to_dict() for a in items], "meta": meta})
