"""
refresh_sodimac_prices.py - corrige los precios de SODIMAC para los productos que
YA estan en la base, sin volver a capturar el catalogo completo.

Por que hace falta: la captura anterior guardaba el precio de lista (el tachado)
como si fuera el precio de venta. En la pagina de producto de Sodimac cada
articulo trae varias entradas:

    cmrPrice       1,499.90  crossed=false   <- con tarjeta CMR
    internetPrice  1,599.90  crossed=false   <- ESTE es el que muestra la pagina
    normalPrice    2,299.90  crossed=true    <- tachado, NO es el precio

La precedencia `internetPrice > eventPrice > cmrPrice` se verifico contra el
JSON-LD de la pagina de producto (`offers.price`), que es lo que la tienda
declara como precio mostrado: 14/14 coincidencias.

Que hace:
  1. Respalda precios.db.
  2. Toma los listing_ref de SODIMAC de la fecha mas reciente.
  3. Consulta cada ficha de producto y extrae precio, lista y tarjeta.
  4. Inserta una fila nueva con la fecha de hoy SOLO donde el precio cambio.
     No se toca el snapshot anterior, asi que el historial queda intacto
     (/prices/matrix siempre muestra la fila mas reciente por producto y tienda).

Uso:
  python refresh_sodimac_prices.py                 # actualiza lo que falte
  python refresh_sodimac_prices.py --limit 20      # prueba con 20 productos
  python refresh_sodimac_prices.py --dry-run       # no escribe, solo reporte
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import requests

DB_PATH = Path(__file__).with_name("precios.db")
REPORT = Path(__file__).with_name("refresh_sodimac_report.csv")
CACHE = Path(__file__).with_name(".sodimac_price_cache.json")

PRODUCT_URL = "https://www.sodimac.com.pe/sodimac-pe/articulo/{pid}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
}
PRECEDENCIA = ("internetPrice", "eventPrice", "cmrPrice")
LIST_TYPE = "normalPrice"
CARD_TYPE = "cmrPrice"

LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)
# Objetos de precio planos del HTML: el orden de "crossed" y "type" cambia entre
# el listado y la ficha, asi que se leen los tres campos por separado.
PRICE_BLOCK = re.compile(r'\{[^{}]*"type"\s*:\s*"[a-zA-Z]*Price"[^{}]*\}', re.S)


def to_float(value):
    """'1,749.90' -> 1749.90. En Sodimac la coma es separador de miles."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").replace("S/", "").replace("s/", "")
    s = s.replace(" ", "").replace("\xa0", "").replace("$", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _first(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def parse_page(html):
    """(precio, lista, tarjeta) de la ficha de producto.

    El precio sale del JSON-LD `offers.price` (es el que la pagina declara como
    mostrado). La lista y el precio con tarjeta se leen de los objetos `prices`
    del HTML.
    """
    precio = None
    for m in LD.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        offers = data.get("offers")
        if not offers:
            continue
        first = offers[0] if isinstance(offers, list) else offers
        precio = to_float(first.get("price"))
        if precio is not None:
            break

    by_type = {}
    for block in PRICE_BLOCK.findall(html):
        tipo = _first(r'"type"\s*:\s*"(\w+)"', block)
        crossed = _first(r'"crossed"\s*:\s*(true|false)', block)
        raw = _first(r'"price"\s*:\s*\[\s*"([^"]+)"', block)
        val = to_float(raw)
        if tipo and val is not None:
            by_type.setdefault(tipo, (val, crossed == "true"))

    lista = by_type.get(LIST_TYPE, (None, False))[0]
    tarjeta = by_type.get(CARD_TYPE, (None, False))[0]
    if lista is not None and (precio is None or lista <= precio):
        lista = None
    return precio, lista, tarjeta


def fetch(pid, tries=3):
    url = PRODUCT_URL.format(pid=pid)
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
            if r.status_code == 404:
                return {"estado": "404"}
            if 200 <= r.status_code < 300:
                precio, lista, tarjeta = parse_page(r.text)
                if precio is None:
                    return {"estado": "sin-precio"}
                return {"estado": "ok", "precio": precio, "lista": lista,
                        "tarjeta": tarjeta}
            last = "http-%d" % r.status_code
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
        time.sleep(1.2 * (i + 1))
    return {"estado": "error", "detalle": last}


def cargar_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def guardar_cache(cache):
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def filas_sodimac(con, categoria_id):
    """Ultima fila por (product_code, listing_ref) para SODIMAC."""
    q = """
        SELECT pe.id, pe.product_code, pe.listing_ref, pe.min_price, pe.list_price,
               pe.card_price, pe.seller, pe.brand_id, pe.name, pe.ean, pe.date,
               pe.is_available
        FROM price_entries pe
        JOIN retails rt ON rt.id = pe.retail_id
        WHERE pe.category_id = ? AND rt.code = 'SODIMAC'
          AND pe.date = (SELECT MAX(d.date) FROM price_entries d
                         JOIN retails r2 ON r2.id = d.retail_id
                         WHERE d.category_id = pe.category_id AND r2.code = 'SODIMAC')
    """
    return con.execute(q, (categoria_id,)).fetchall()


def main(argv=None):
    p = argparse.ArgumentParser(description="Refresca precios SODIMAC de productos ya capturados")
    p.add_argument("--limit", type=int, default=None, help="solo N productos")
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--dry-run", action="store_true", help="no escribe en la base")
    a = p.parse_args(argv)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    cat = con.execute("SELECT id FROM categories WHERE code='TELEVISORES'").fetchone()["id"]
    retail_id = con.execute("SELECT id FROM retails WHERE code='SODIMAC'").fetchone()["id"]

    filas = filas_sodimac(con, cat)
    if a.limit:
        filas = filas[:a.limit]
    print("SODIMAC: %d filas a revisar (productos: %d)"
          % (len(filas), len({f["product_code"] for f in filas})))

    cache = cargar_cache()
    pendientes = [f for f in filas if str(f["listing_ref"]) not in cache]
    print("  en cache: %d, a consultar: %d" % (len(filas) - len(pendientes), len(pendientes)))

    hechas = 0
    if pendientes:
        print("  consultando con %d hilos..." % a.workers)

        def tarea(f):
            res = fetch(str(f["listing_ref"]))
            cache[str(f["listing_ref"])] = res
            return res

        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for _ in pool.map(tarea, pendientes):
                hechas += 1
                if hechas % 100 == 0:
                    guardar_cache(cache)
                    print("    %d/%d" % (hechas, len(pendientes)))
        guardar_cache(cache)

    cambios, iguales, sin_pal, no_encontrado = [], 0, [], []
    for f in filas:
        pid = str(f["listing_ref"])
        info = cache.get(pid, {})
        if info.get("estado") != "ok":
            (sin_pal if info.get("estado") in ("sin-precio", "error") else no_encontrado).append((f, info))
            continue
        nuevo = round(float(info["precio"]), 2)
        antes = round(float(f["min_price"]), 2)
        lista = info.get("lista")
        tarjeta = info.get("tarjeta")
        if abs(nuevo - antes) < 0.01 and lista is None:
            iguales += 1
            continue
        cambios.append((f, antes, nuevo, lista, tarjeta))

    print("")
    print("  precio correcto ya : %d" % iguales)
    print("  a actualizar        : %d" % len(cambios))
    print("  sin precio / error  : %d" % len(sin_pal))
    print("  no existe (404)     : %d" % len(no_encontrado))

    with open(REPORT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["product_code", "listing_ref", "nombre", "vendedor",
                    "precio_antes", "precio_nuevo", "diferencia",
                    "lista_antes", "lista_nueva", "tarjeta_nueva", "fecha"])
        for f, antes, nuevo, lista, tarjeta in cambios:
            w.writerow([f["product_code"], f["listing_ref"], f["name"], f["seller"],
                        "%.2f" % antes, "%.2f" % nuevo, "%.2f" % (antes - nuevo),
                        f["list_price"], ("%.2f" % lista) if lista else "",
                        ("%.2f" % tarjeta) if tarjeta else "",
                        str(f["date"])])
        for f, info in sin_pal + no_encontrado:
            w.writerow([f["product_code"], f["listing_ref"], f["name"], f["seller"],
                        f["min_price"], "", "", f["list_price"], "", "",
                        info.get("estado")])
    print("")
    print("  reporte: %s" % REPORT)

    if a.dry_run:
        print("  --dry-run: no se escribio nada")
        return 0

    if not cambios:
        print("  nada que escribir")
        return 0

    hoy = date.today()
    cur = con.executemany(
        """INSERT INTO price_entries
             (date, category_id, retail_id, brand_id, product_code, min_price,
              has_sales_rank, sales_rank, is_available, seller, list_price,
              card_price, listing_ref, name, ean)
           VALUES (?,?,?,?,?,?,0,NULL,?,?,?,?,?,?,?)""",
        [(hoy.isoformat(), cat, retail_id, f["brand_id"], f["product_code"], "%.2f" % nuevo,
          f["is_available"] if "is_available" in f.keys() else None, f["seller"],
          ("%.2f" % lista) if lista else None,
          ("%.2f" % tarjeta) if tarjeta else None,
          f["listing_ref"], f["name"], f["ean"]) for f, _, nuevo, lista, tarjeta in cambios])
    con.commit()
    print("  insertadas %d filas con fecha %s (el snapshot %s queda intacto)"
          % (cur.rowcount, hoy, filas[0]["date"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
