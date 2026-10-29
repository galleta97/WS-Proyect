"""
cargar_ferreteria.py - carga en precios.db productos de ferretería con su
precio actual en Promart, Sodimac y, si también los venden, Oechsle y Plaza Vea.

Parte del cruce Promart -> Sodimac ya hecho (cruce_promart_sodimac_v2.csv) y
NO confía ciegamente en él: cada par se vuelve a validar con los datos de hoy.

  1. Promart: se consulta su API por skuId (precio, lista, stock, EAN).
  2. Sodimac: se lee la ficha del candidato (precio del JSON-LD, GTIN, marca).
  3. El par se acepta si:
       - los dos EAN son válidos e iguales            -> match "ean"
       - o, sin EAN comparable (Sodimac no lo publica): coincide la marca,
         el nombre se parece, las medidas no se contradicen (pulgadas, kg,
         galones, W, A, mm, grano, número de alambre...), los colores no se
         contradicen y el precio está entre 0.75 y 1.33 veces el de Promart
                                                        -> match "nombre"
     Un EAN distinto descarta el par aunque los nombres se parezcan.
     Cada producto de Sodimac se usa una sola vez (gana el par más parecido).
  4. Con el EAN de Promart busca el mismo producto en Oechsle y Plaza Vea
     (VTEX); esa coincidencia es exacta, así que sirve aunque Sodimac falle.
  5. Carga los productos con precio en al menos 2 tiendas: una categoría por
     área (PINTURAS, GASFITERIA, ...), la marca de Promart para todas las
     tiendas y el EAN (o el SKU de Promart) como código común.

Antes de escribir respalda precios.db. Si se ejecuta dos veces el mismo día,
reemplaza los precios de ese día en vez de duplicarlos.

Uso (desde la carpeta del proyecto, en una red con acceso a las tiendas):
  python cargar_ferreteria.py --dry-run      # consulta y valida, no escribe
  python cargar_ferreteria.py                # consulta, valida y carga
  python cargar_ferreteria.py --limit 20     # prueba con 20 pares
  python cargar_ferreteria.py --sin-extras   # solo Promart y Sodimac

Deja el detalle de cada par en carga_ferreteria_report.csv.
"""

import argparse
import csv
import html as htmllib
import io
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "precios.db"
INPUT = BASE / "cruce_promart_sodimac_v2.csv"
REPORT = BASE / "carga_ferreteria_report.csv"
CACHE = BASE / f".ferreteria_cache_{date.today():%Y%m%d}.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "es-PE,es;q=0.9",
}
VTEX = {
    "PROMART": "https://www.promart.pe",
    "OECHSLE": "https://www.oechsle.pe",
    "PLAZAVEA": "https://www.plazavea.com.pe",
}
VTEX_SEARCH = "/api/catalog_system/pub/products/search/?fq={field}:{value}"
SODIMAC_PRODUCT = "https://www.sodimac.com.pe/sodimac-pe/articulo/{pid}"
EXTRA_STORES = ("OECHSLE", "PLAZAVEA")
MATCHES_TO_CHECK = ("sku-exacto", "ok")

# Validación por nombre (cuando no hay EAN comparable)
MIN_NAME_SIMILARITY = 0.30
PRICE_RATIO = (0.75, 1.33)         # el precio de Sodimac debe estar dentro de este rango del de Promart

STOP = {"PARA", "CON", "DEL", "LOS", "LAS", "POR", "SIN", "UNIDAD", "UND", "PACK", "COLOR",
        "MODELO", "NUEVO", "TIPO", "MARCA", "BLANCO", "NEGRO", "GRIS"}
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)
PRICE_BLOCK = re.compile(r'\{[^{}]*"type"\s*:\s*"[a-zA-Z]*Price"[^{}]*\}', re.S)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def valid_ean(code):
    """EAN-13 real: 13 dígitos, dígito verificador correcto, sin prefijo 2 (uso interno)."""
    digits = re.sub(r"\D", "", str(code or ""))
    if len(digits) != 13 or digits.startswith("2"):
        return None
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return digits if (10 - total % 10) % 10 == int(digits[12]) else None


def norm_brand(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def tokens(text):
    clean = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ ]", " ", str(text or "")).upper()
    return {t for t in clean.split() if len(t) > 2 and t not in STOP and not t.isdigit()}


def similarity(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


UNIT_ALIASES = {
    "GL": "GL", "GAL": "GL", "GALON": "GL", "GALONES": "GL",
    "KG": "KG", "KILO": "KG", "KILOS": "KG", "G": "G", "GR": "G",
    "L": "L", "LT": "L", "LTS": "L", "LITRO": "L", "LITROS": "L", "ML": "ML",
    "M": "M", "MT": "M", "MTS": "M", "METRO": "M", "METROS": "M", "CM": "CM", "MM": "MM",
    "W": "W", "V": "V", "A": "A", "HP": "HP", "AWG": "AWG",
    "PULG": "PULG", "PULGADA": "PULG", "PULGADAS": "PULG", "PZ": "PZ", "PZAS": "PZ", "PIEZAS": "PZ",
}
COLORS = {"BLANCO", "NEGRO", "GRIS", "AMARILLO", "ROJO", "AZUL", "VERDE", "DORADO", "PLATEADO",
          "CROMADO", "TRANSPARENTE", "MARRON", "CAFE", "NARANJA", "TERRACOTA", "BEIGE", "CREMA"}


def _num(text):
    """'1.10' -> '1.1', '.14' -> '0.14', '1-1/2' se deja igual."""
    if "/" in text:
        return text
    try:
        return ("%g" % float(text))
    except ValueError:
        return text


def measures(text):
    """Medidas de un nombre agrupadas por unidad: {'PULG': {'1/2'}, 'KG': {'25'}, 'DIM': {...}}."""
    s = " " + str(text or "").upper().replace(",", ".") + " "
    s = s.replace("&QUOT;", '"').replace("&APOS;", "'")
    s = re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", s)                  # 1 /2 -> 1/2
    s = re.sub(r"(\d+)\s+(\d+/\d+)", r"\1-\2", s)                  # 1 1/2 -> 1-1/2
    s = re.sub(r"(\d)\s*(\"|''|’’)", r"\1 PULG ", s)               # 2" -> 2 PULG
    s = re.sub(r"(\d)\s*\*\s*(\d)", r"\1X\2", s)                  # 2*3 -> 2X3
    out = {}
    def add(unit, value):
        out.setdefault(unit, set()).add(value)
    for m in re.finditer(r"(?:#|\bN[º°O]\.?\s*|\bN[ÚU]MERO\s*|\bNRO\.?\s*)(\d+)", s):  # alambre #8 / Nº 16 / Número 8
        add("NUM", m.group(1))
    for m in re.finditer(r"GRANO\s*(\d+)", s):
        add("GRANO", m.group(1))
    for m in re.finditer(r"(\d*\.?\d+(?:\s*X\s*\d*\.?\d+)+)", s):   # 20X12, 1.85X2.44
        for part in re.split(r"\s*X\s*", m.group(1)):
            add("DIM", _num(part))
    for m in re.finditer(r"(\d+(?:-\d+/\d+)?(?:/\d+)?(?:\.\d+)?)\s*([A-Z]+)\b", s):
        unit = UNIT_ALIASES.get(m.group(2))
        if unit:
            add(unit, _num(m.group(1)))
    return out


def measures_conflict(a, b):
    """Hay conflicto si una misma unidad aparece en los dos nombres sin ningún valor en común."""
    for unit in set(a) & set(b):
        if not (a[unit] & b[unit]):
            return f"{unit}: {'/'.join(sorted(a[unit]))} vs {'/'.join(sorted(b[unit]))}"
    return None


def colors(text):
    clean = re.sub(r"[^A-ZÁÉÍÓÚÑ ]", " ", str(text or "").upper())
    clean = clean.translate(str.maketrans("ÁÉÍÓÚ", "AEIOU"))
    return {w for w in clean.split() if w in COLORS}


def to_float(value):
    """'1,749.90' -> 1749.9 (en estas tiendas la coma separa miles)."""
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = re.sub(r"[^\d.,]", "", str(value or "")).replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


class Fetcher:
    """GET con reintentos, pausa entre llamadas y caché del día (para poder reanudar).

    Con `parser`, la caché guarda solo lo que devuelve el parser (unos pocos
    datos) y no el HTML completo de la página.
    """

    def __init__(self, delay, use_cache=True, cache_only=False):
        self.delay = delay
        self.cache_only = cache_only
        self.cache = {}
        if use_cache and CACHE.exists():
            try:
                self.cache = json.loads(CACHE.read_text(encoding="utf-8"))
            except ValueError:
                self.cache = {}
        # Las cachés anteriores guardaban el HTML completo de Sodimac (~1 MB por
        # ficha): se reducen una sola vez a los datos extraídos.
        legacy = [k for k, v in self.cache.items() if k.startswith("SODIMAC|") and "body" in v]
        for key in legacy:
            entry = self.cache[key]
            self.cache[key] = {"status": entry["status"],
                               "data": parse_sodimac(entry["body"]) if entry.get("body") else None}
        if legacy:
            self.save()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.calls = 0

    def get(self, url, kind, parser=None):
        key = f"{kind}|{url}"
        if key in self.cache:
            entry = self.cache[key]
            if parser and "body" in entry:          # caché antigua con el HTML completo
                entry = {"status": entry["status"],
                         "data": parser(entry["body"]) if entry.get("body") else None}
                self.cache[key] = entry
            return entry
        if self.cache_only:
            return {"status": "sin-cache", "body": None, "data": None}
        result = {"status": None, "body": None}
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=30)
                result = {"status": r.status_code, "body": r.text if r.status_code == 200 else None}
                if r.status_code in (200, 404):
                    break
            except requests.RequestException as exc:
                result = {"status": type(exc).__name__, "body": None}
            time.sleep(1.5 * (attempt + 1))
        self.calls += 1
        time.sleep(self.delay)
        if parser:
            result = {"status": result["status"],
                      "data": parser(result["body"]) if result.get("body") else None}
        if result["status"] in (200, 404):
            self.cache[key] = result
        return result

    def save(self):
        # Se escribe en un archivo temporal y luego se reemplaza: si el proceso
        # se interrumpe a mitad, la caché anterior queda intacta.
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE)


# ---------------------------------------------------------------------------
# Tiendas
# ---------------------------------------------------------------------------

def parse_vtex(products, want_sku=None, want_ean=None):
    """Precio de un producto VTEX. Elige el item del SKU o del EAN pedido."""
    for product in products or []:
        for item in product.get("items") or []:
            item_ean = valid_ean(item.get("ean"))
            if want_sku and str(item.get("itemId")) != str(want_sku):
                continue
            if want_ean and item_ean != want_ean:
                continue
            sellers = item.get("sellers") or []
            seller = next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else None)
            offer = (seller or {}).get("commertialOffer") or {}
            price = to_float(offer.get("Price"))
            if price is None:
                continue
            list_price = to_float(offer.get("ListPrice"))
            available = bool(offer.get("IsAvailable")) or (offer.get("AvailableQuantity") or 0) > 0
            return {
                "name": product.get("productName") or "",
                "brand": (product.get("brand") or "").strip(),
                "ean": item_ean,
                "price": price,
                "list_price": list_price if list_price and list_price > price else None,
                "available": available,
                "seller": (seller or {}).get("sellerName"),
                "ref": str(item.get("itemId") or ""),
                "link": product.get("link") or "",
            }
    return None


def vtex_lookup(fetcher, store, field, value, want_sku=None, want_ean=None):
    url = VTEX[store] + VTEX_SEARCH.format(field=field, value=value)
    res = fetcher.get(url, store)
    if res["status"] != 200 or not res["body"]:
        return None
    try:
        data = json.loads(res["body"])
    except ValueError:
        return None
    found = parse_vtex(data, want_sku=want_sku, want_ean=want_ean)
    if found and not found["link"]:
        found["link"] = url
    return found


def parse_sodimac(html):
    """Nombre, marca, GTIN, precio (JSON-LD), lista y tarjeta de una ficha de Sodimac."""
    info = {"name": "", "brand": "", "ean": None, "price": None, "available": None}
    for block in LD.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict) or node.get("@type") not in ("Product", ["Product"]):
                continue
            info["name"] = htmllib.unescape(node.get("name") or info["name"])
            brand = node.get("brand")
            info["brand"] = (brand.get("name") if isinstance(brand, dict) else brand) or info["brand"]
            info["ean"] = valid_ean(node.get("gtin13") or node.get("gtin") or node.get("gtin12"))
            offers = node.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict):
                info["price"] = to_float(offer.get("price") or offer.get("lowPrice"))
                avail = str(offer.get("availability") or "")
                info["available"] = ("InStock" in avail) if avail else None
    by_type = {}
    for block in PRICE_BLOCK.findall(html):
        tipo = re.search(r'"type"\s*:\s*"(\w+)"', block)
        raw = re.search(r'"price"\s*:\s*\[\s*"([^"]+)"', block)
        if tipo and raw and to_float(raw.group(1)) is not None:
            by_type.setdefault(tipo.group(1), to_float(raw.group(1)))
    lista = by_type.get("normalPrice")
    info["list_price"] = lista if lista and info["price"] and lista > info["price"] else None
    info["card_price"] = by_type.get("cmrPrice")
    return info


def sodimac_lookup(fetcher, product_id):
    url = SODIMAC_PRODUCT.format(pid=product_id)
    res = fetcher.get(url, "SODIMAC", parser=parse_sodimac)
    info = dict(res.get("data") or {})
    if res["status"] != 200 or info.get("price") is None:
        return None
    info["ref"] = str(product_id)
    info["link"] = url
    info["seller"] = None
    return info


# ---------------------------------------------------------------------------
# Validación del par Promart / Sodimac
# ---------------------------------------------------------------------------

def validate_pair(promart, sodimac):
    """Devuelve (aceptado, tipo_de_match, motivo, similitud)."""
    ratio = sodimac["price"] / promart["price"]
    if promart["ean"] and sodimac["ean"]:
        if promart["ean"] == sodimac["ean"]:
            return True, "ean", "mismo EAN", 1.0
        return False, "", f"EAN distinto ({promart['ean']} vs {sodimac['ean']})", 0.0
    same_brand = norm_brand(promart["brand"]) and norm_brand(promart["brand"]) == norm_brand(sodimac["brand"])
    sim = similarity(promart["name"] + " " + promart["brand"], sodimac["name"] + " " + sodimac["brand"])
    if not same_brand:
        return False, "", f"marca distinta ({promart['brand']} vs {sodimac['brand']})", sim
    conflict = measures_conflict(measures(promart["name"]), measures(sodimac["name"]))
    if conflict:
        return False, "", f"medidas distintas ({conflict})", sim
    ca, cb = colors(promart["name"]), colors(sodimac["name"])
    if ca and cb and not (ca & cb):
        return False, "", f"color distinto ({'/'.join(sorted(ca))} vs {'/'.join(sorted(cb))})", sim
    if not PRICE_RATIO[0] <= ratio <= PRICE_RATIO[1]:
        return False, "", f"precio fuera de rango (x{ratio:.2f})", sim
    if sim < MIN_NAME_SIMILARITY:
        return False, "", f"nombres poco parecidos ({sim:.2f})", sim
    return True, "nombre", f"marca, medidas y nombre ({sim:.2f}), precio x{ratio:.2f}", sim


# ---------------------------------------------------------------------------
# Carga en la base
# ---------------------------------------------------------------------------

def backup(db_path):
    dest = db_path.with_name(f"{db_path.stem}.backup-ferreteria-{datetime.now():%Y%m%d_%H%M%S}{db_path.suffix}")
    shutil.copy2(db_path, dest)
    return dest


def get_or_create(con, table, code, extra=None):
    row = con.execute(f"SELECT id FROM {table} WHERE code = ?", (code,)).fetchone()
    if row:
        return row[0]
    cols, vals = ["code"], [code]
    for k, v in (extra or {}).items():
        cols.append(k)
        vals.append(v)
    cur = con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})", vals)
    return cur.lastrowid


def load(products, today):
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    retail_ids = dict(con.execute("SELECT code, id FROM retails").fetchall())
    rows = 0
    with con:
        for p in products:
            cat_id = get_or_create(con, "categories", p["category"])
            brand_id = get_or_create(con, "brands", p["brand"])
            for store, info in p["stores"].items():
                retail_id = retail_ids[store]
                con.execute("INSERT OR IGNORE INTO brand_categories VALUES (?, ?)", (brand_id, cat_id))
                con.execute("INSERT OR IGNORE INTO brand_retails VALUES (?, ?)", (brand_id, retail_id))
                con.execute("DELETE FROM price_entries WHERE date = ? AND retail_id = ? AND product_code = ?",
                            (today.isoformat(), retail_id, p["code"]))
                con.execute(
                    """INSERT INTO price_entries (date, category_id, retail_id, brand_id, product_code,
                           min_price, has_sales_rank, sales_rank, is_available, seller, list_price,
                           card_price, listing_ref, name, ean, url)
                       VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (today.isoformat(), cat_id, retail_id, brand_id, p["code"], info["price"],
                     info.get("available"), info.get("seller"), info.get("list_price"),
                     info.get("card_price"), info.get("ref"), (info.get("name") or "")[:300],
                     p["ean"], (info.get("link") or "")[:300]))
                rows += 1
    con.close()
    return rows


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="solo los primeros N pares")
    ap.add_argument("--dry-run", action="store_true", help="consulta y valida, pero no escribe en la base")
    ap.add_argument("--sin-extras", action="store_true", help="no buscar en Oechsle ni Plaza Vea")
    ap.add_argument("--delay", type=float, default=0.6, help="pausa entre consultas en segundos (por defecto 0.6)")
    ap.add_argument("--sin-cache", action="store_true", help="ignora las respuestas guardadas hoy")
    ap.add_argument("--solo-cache", action="store_true",
                    help="revalida con las respuestas ya guardadas hoy, sin consultar las tiendas")
    args = ap.parse_args(argv)

    if not INPUT.exists():
        sys.exit(f"No encuentro {INPUT.name}. Ejecuta primero cruce_promart_sodimac.py.")
    with INPUT.open(encoding="utf-8-sig", newline="") as f:
        pairs = [r for r in csv.DictReader(f) if r.get("match") in MATCHES_TO_CHECK]
    if args.limit:
        pairs = pairs[:args.limit]
    print(f"Pares a validar: {len(pairs)}")

    fetcher = Fetcher(args.delay, use_cache=not args.sin_cache, cache_only=args.solo_cache)
    today = date.today()
    candidates, report = [], []
    try:
        for i, pair in enumerate(pairs, 1):
            area = (pair.get("area") or "FERRETERIA").strip().upper()
            line = {"area": area, "sku_promart": pair["sku_excel"],
                    "producto": pair["descripcion_excel"], "sodimac_id": pair["candidato_productId"]}
            promart = vtex_lookup(fetcher, "PROMART", "skuId", pair["sku_excel"], want_sku=pair["sku_excel"])
            if promart is None:
                report.append({**line, "estado": "descartado", "motivo": "sin precio en Promart"})
                continue
            line["nombre_promart"] = promart["name"]
            stores = {"PROMART": promart}
            sodimac = sodimac_lookup(fetcher, pair["candidato_productId"]) if pair["candidato_productId"] else None
            sod_ok, kind, reason, sim = False, "", "sin precio en Sodimac", 0.0
            if sodimac is not None:
                line["nombre_sodimac"] = sodimac["name"]
                sod_ok, kind, reason, sim = validate_pair(promart, sodimac)
            ean = promart["ean"] or (sodimac or {}).get("ean")
            if ean and not args.sin_extras:
                for store in EXTRA_STORES:
                    found = vtex_lookup(fetcher, store, "alternateIds_Ean", ean, want_ean=ean)
                    if found:
                        stores[store] = found
            candidates.append({"line": line, "promart": promart, "sodimac": sodimac if sod_ok else None,
                               "kind": kind, "reason": reason, "sim": sim, "stores": stores, "ean": ean,
                               "area": area, "sku": pair["sku_excel"]})
            if i % 10 == 0:
                fetcher.save()
                print(f"  {i}/{len(pairs)} revisados")
    finally:
        fetcher.save()

    # Cada producto de Sodimac se usa una sola vez: gana el par con el nombre
    # más parecido y, si empatan, el de precio más cercano.
    by_sodimac = {}
    for c in candidates:
        if c["sodimac"]:
            by_sodimac.setdefault(c["sodimac"]["ref"], []).append(c)
    for group in by_sodimac.values():
        group.sort(key=lambda c: (-c["sim"], abs(1 - c["sodimac"]["price"] / c["promart"]["price"])))
        for loser in group[1:]:
            loser["sodimac"] = None
            loser["reason"] = f"el producto de Sodimac ya se asignó a otro SKU ({group[0]['sku']})"

    products = []
    for c in candidates:
        stores = dict(c["stores"])
        if c["sodimac"]:
            stores["SODIMAC"] = c["sodimac"]
        extras = [s for s in stores if s in EXTRA_STORES]
        if len(stores) < 2:
            report.append({**c["line"], "estado": "descartado", "motivo": c["reason"]})
            continue
        code = c["ean"] or f"PM{c['sku']}"
        products.append({"code": code, "ean": c["ean"], "category": c["area"],
                         "brand": c["promart"]["brand"].upper() or "GENERICO", "stores": stores})
        how = (f"Sodimac por {c['kind']}: {c['reason']}" if c["sodimac"]
               else f"Sodimac descartado ({c['reason']})")
        if extras:
            how += f"; EAN en {', '.join(extras)}"
        report.append({**c["line"], "estado": "aceptado", "motivo": how, "tiendas": "+".join(stores),
                       "codigo": code, "precio_promart": c["promart"]["price"],
                       "precio_sodimac": c["sodimac"]["price"] if c["sodimac"] else ""})

    fields = ["area", "sku_promart", "producto", "nombre_promart", "sodimac_id", "nombre_sodimac",
              "estado", "motivo", "tiendas", "codigo", "precio_promart", "precio_sodimac"]
    with REPORT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(report)

    by_count = {}
    for p in products:
        by_count[len(p["stores"])] = by_count.get(len(p["stores"]), 0) + 1
    print(f"\nAceptados: {len(products)} de {len(pairs)} "
          f"(por cantidad de tiendas: {dict(sorted(by_count.items()))}) · consultas: {fetcher.calls}")
    print(f"Detalle: {REPORT.name}")
    if len(products) < 50:
        print("Atención: quedaron menos de 50 productos. Revisa los motivos en el reporte.")

    if args.dry_run or not products:
        print("No se escribió nada en la base." + (" (--dry-run)" if args.dry_run else ""))
        return
    dest = backup(DB_PATH)
    rows = load(products, today)
    print(f"Respaldo: {dest.name}\nCargados {rows} precios de {len(products)} productos con fecha {today:%d/%m/%Y}.")


if __name__ == "__main__":
    main()
