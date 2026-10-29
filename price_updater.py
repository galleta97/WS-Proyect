"""
Ingesta de precios con detección de cambios (Fase 3) y de stock
(Fase 4), más el "actualizador" en background con threading (Fase 3).

CÓMO CONECTAR TU SCRAPER REAL:
En vez del watcher de demo de abajo (que genera variaciones aleatorias
solo para poder probar el mecanismo end-to-end sin datos reales), tu
scraper real debe llamar a `ingest_price(...)` cada vez que obtenga un
precio nuevo de una tienda. Esa función ya hace todo lo demás: compara
contra el último precio/stock guardado, guarda el nuevo registro, crea
la(s) alerta(s) si algo cambió, y dispara la notificación.

DÓNDE SACAR EL CAMPO DE STOCK DE LA API DE VTEX (Fase 4):
La API pública de VTEX (la misma que ya usa tu scraper para precios en
PlazaVea/Promart/Metro) devuelve la disponibilidad dentro de cada
"seller" del producto. La forma típica de la respuesta es:

    {
      "items": [
        {
          "sellers": [
            {
              "commertialOffer": {
                "Price": 1899.90,
                "IsAvailable": true,
                "AvailableQuantity": 12
              }
            }
          ]
        }
      ]
    }

Es decir: `items[0]["sellers"][0]["commertialOffer"]["IsAvailable"]`
(booleano — así lo devuelve VTEX literalmente). Si quieres un umbral
distinto a "hay o no hay", `AvailableQuantity` también viene ahí (ej.
tratar <5 unidades como "stock bajo" es una regla tuya, no de la API).

Ejemplo desde un scraper real:
    from price_updater import ingest_price
    ingest_price(
        product_code="UN65M80HAGXPE",
        retail_code="FALABELLA",
        category_code="TV LED",
        brand_code="SAMSUNG",
        new_price=1899.90,
        is_available=item["sellers"][0]["commertialOffer"]["IsAvailable"],
    )
"""

import os
import random
import threading
import time
from datetime import date, datetime

from extensions import db
from models import Brand, Category, PriceAlert, PriceEntry, Retail
from notifications import notify_alert


def _stock_label(is_available):
    if is_available is None:
        return None
    return "disponible" if is_available else "agotado"


def ingest_price(product_code, retail_code, category_code=None, brand_code=None,
                  new_price=None, is_available=None, seller=None, scrape_date=None):
    """
    Registra un precio (y opcionalmente stock) recién scrapeado para
    (product_code, retail_code). Si el precio o la disponibilidad
    difieren de lo último guardado para ese mismo par, crea una alerta
    por cada cambio detectado y dispara la notificación configurada.

    `is_available`: True/False si tu scraper trae ese dato, o None si no
    lo tienes todavía (en ese caso simplemente no se evalúa cambio de
    stock, sin romper nada).

    Devuelve una lista de PriceAlert creadas (puede ser 0, 1, o 2 si
    cambiaron precio Y stock a la vez). La primera vez que se ve un SKU
    en una tienda nunca genera alerta — no hay "antes" con qué comparar.
    """
    scrape_date = scrape_date or date.today()
    retail = Retail.query.filter_by(code=retail_code).first()
    if retail is None:
        raise ValueError(f"Retail desconocido: {retail_code}")

    last_entry = (
        PriceEntry.query
        .filter_by(product_code=product_code, retail_id=retail.id)
        .order_by(PriceEntry.date.desc(), PriceEntry.id.desc())  # id desempata varias corridas el mismo día
        .first()
    )

    category = Category.query.filter_by(code=category_code).first() if category_code else (
        last_entry.category if last_entry else None
    )
    brand = Brand.query.filter_by(code=brand_code).first() if brand_code else (
        last_entry.brand if last_entry else None
    )

    new_entry = PriceEntry(
        date=scrape_date,
        category_id=(category.id if category else (last_entry.category_id if last_entry else None)),
        retail_id=retail.id,
        brand_id=(brand.id if brand else (last_entry.brand_id if last_entry else None)),
        product_code=product_code,
        min_price=new_price,
        is_available=is_available,
        # Si el scraper no informa vendedor, se conserva el último conocido
        # para esa tienda y producto en vez de borrarlo.
        seller=seller if seller is not None else (last_entry.seller if last_entry else None),
    )
    db.session.add(new_entry)

    alerts = []

    if last_entry is not None and float(last_entry.min_price) != float(new_price):
        price_alert = PriceAlert(
            product_code=product_code,
            retail_id=retail.id,
            alert_type="price_change",
            previous_value=f"{float(last_entry.min_price):.2f}",
            new_value=f"{float(new_price):.2f}",
        )
        price_alert.retail = retail
        alerts.append(price_alert)

    if (last_entry is not None and is_available is not None
            and last_entry.is_available is not None
            and last_entry.is_available != is_available):
        stock_alert = PriceAlert(
            product_code=product_code,
            retail_id=retail.id,
            alert_type="stock_change",
            previous_value=_stock_label(last_entry.is_available),
            new_value=_stock_label(is_available),
        )
        stock_alert.retail = retail
        alerts.append(stock_alert)

    for alert in alerts:
        db.session.add(alert)
        notify_alert(alert)

    db.session.commit()
    return alerts


# ---------------------------------------------------------------------------
# Watcher de demo (threading) — simula que llegan precios nuevos cada
# cierto intervalo, para poder ver el mecanismo de alertas funcionando sin
# depender de un scraper real todavía.
# ---------------------------------------------------------------------------

_watcher_thread = None
_watcher_stop = threading.Event()


def _watcher_loop(app, interval_seconds):
    with app.app_context():
        while not _watcher_stop.is_set():
            # Espera primero, simula después — así el primer chequeo
            # ocurre a los N segundos de activar el watcher, no de inmediato.
            if _watcher_stop.wait(interval_seconds):
                break
            try:
                _simulate_one_price_update()
            except Exception as e:
                print(f"[price_watcher] error en la simulación: {e}")


def _simulate_one_price_update():
    """Toma un registro de precio real al azar y le aplica una variación
    pequeña, como si el scraper acabara de traer un valor nuevo. De vez en
    cuando también cambia el estado de stock, para poder ver esas alertas
    funcionando sin depender de un scraper real todavía."""
    sample = PriceEntry.query.order_by(db.func.random()).first()
    if sample is None:
        return

    variation = random.uniform(-0.05, 0.05)  # +/- 5%
    new_price = round(float(sample.min_price) * (1 + variation), 2)

    # Simula stock: si no sabíamos su disponibilidad, arranca en True;
    # ~15% de las veces se lo "voltea" para generar una alerta de stock.
    previous_availability = sample.is_available if sample.is_available is not None else True
    new_availability = (not previous_availability) if random.random() < 0.15 else previous_availability

    alerts = ingest_price(
        product_code=sample.product_code,
        retail_code=sample.retail.code,
        category_code=sample.category.code if sample.category else None,
        brand_code=sample.brand.code if sample.brand else None,
        new_price=new_price,
        is_available=new_availability,
        scrape_date=date.today(),
    )
    for alert in alerts:
        kind = "stock" if alert.alert_type == "stock_change" else "precio"
        print(f"[price_watcher] ({kind}) {sample.product_code} en {sample.retail.code}: "
              f"{alert.previous_value} -> {alert.new_value}")


def start_price_watcher(app):
    """
    Arranca el hilo en background. Se activa solo si ENABLE_PRICE_WATCHER
    está en 'true' — así no corre sin querer en cada arranque del server.
    El intervalo se controla con PRICE_WATCHER_INTERVAL_SECONDS (default 30s,
    pensado solo para poder ver alertas aparecer rápido en desarrollo; un
    scraper real correría con su propia cadencia, ej. una vez al día).
    """
    global _watcher_thread
    if os.environ.get("ENABLE_PRICE_WATCHER", "false").lower() != "true":
        return

    interval = int(os.environ.get("PRICE_WATCHER_INTERVAL_SECONDS", "30"))
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(
        target=_watcher_loop, args=(app, interval), daemon=True
    )
    _watcher_thread.start()
    print(f"[price_watcher] activado — revisando cada {interval}s (modo demo)")


def stop_price_watcher():
    _watcher_stop.set()
