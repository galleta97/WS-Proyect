"""
import_capture.py - carga en el dashboard las capturas REALES hechas con
clase3.py / probe_stores.py (los productos.csv de la carpeta probe_out).

Une los listados de las distintas tiendas en un mismo modelo cuando comparten
un EAN valido o un codigo de modelo (en el atributo o dentro del nombre).

Uso (desde la carpeta del proyecto):

  python import_capture.py --probe-out C:\\ruta\\a\\probe_out --nuevo

  --probe-out   carpeta probe_out donde guardaste las capturas (toma la mas
                reciente de cada tienda: carpetas <dominio>_cat_*)
  --nuevo       BORRA la base actual (incluidos los datos de ejemplo) y la crea
                solo con datos reales. Recrea el usuario demo@vigia.pe.
                Sin esta opcion, agrega a lo que ya existe.
"""

import argparse
import csv
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from app import create_app
from capture_utils import brand_key, brands_compatible, cluster_rows, is_tv, model_tokens, norm_model, parse_price, usable_model, valid_ean
from extensions import db
from models import Brand, Category, PriceEntry, Retail, User

CATEGORY_NAME = "TELEVISORES"
RETAIL_COLORS = {
    "PROMART": "#f97316", "METRO": "#a855f7", "SODIMAC": "#e11d48",
    "FALABELLA": "#22c55e", "PLAZAVEA": "#eab308", "TOTTUS": "#0ea5e9",
    "OECHSLE": "#ec4899", "CARSA": "#14b8a6", "HIRAOKA": "#dc2626",
    "LACURACAO": "#f59e0b", "EFE": "#2563eb", "RIPLEY": "#7c3aed",
}
# El dominio no siempre coincide con el nombre de la tienda (simple.ripley.com.pe -> RIPLEY)
RETAIL_ALIASES = {"SIMPLE": "RIPLEY", "LACURACAO": "LACURACAO", "TIENDASEFE": "EFE"}


def latest_captures(probe_out):
    """{tienda: ruta al productos.csv mas reciente} para carpetas www.<tienda>_cat_*."""
    found = {}
    for csv_path in Path(probe_out).glob("*_cat_*/productos.csv"):
        store = csv_path.parent.name.split("_")[0]
        mtime = csv_path.stat().st_mtime
        if store not in found or mtime > found[store][0]:
            found[store] = (mtime, csv_path)
    return {store: path for store, (_, path) in found.items()}


def capture_date(csv_path):
    m = re.search(r"_(\d{8})_\d{6}$", csv_path.parent.name)
    return datetime.strptime(m.group(1), "%Y%m%d").date() if m else date.today()


def retail_code(store):
    code = store.replace("www.", "").split(".")[0].upper()
    return RETAIL_ALIASES.get(code, code)


def canonical_code(members):
    models = Counter(
        norm_model(r.get("modelo")) for r in members if usable_model(norm_model(r.get("modelo")))
    )
    if models:
        # el mas frecuente; si empatan, el mas especifico (el codigo mas largo)
        return max(models.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
    tokens = Counter(t for r in members for t in model_tokens(r.get("nombre")))
    if tokens:
        return tokens.most_common(1)[0][0]
    eans = Counter(r["ean"] for r in members if r.get("ean") and valid_ean(r["ean"]))
    if eans:
        return eans.most_common(1)[0][0]
    first = members[0]
    return f"{retail_code(first['_store'])}-{first.get('product_id')}"


def read_rows(captures):
    rows, skipped = [], Counter()
    for store, path in captures.items():
        stamp = capture_date(path)
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if not is_tv(r.get("nombre")):
                    skipped["no es televisor"] += 1
                    continue
                price = parse_price(r.get("precio"))
                if price is None or price <= 0:
                    skipped["sin precio"] += 1
                    continue
                r["_store"], r["_date"], r["_price"] = store, stamp, price
                rows.append(r)
    return rows, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carga capturas reales en el dashboard")
    parser.add_argument("--probe-out", required=True, help="carpeta probe_out con las capturas")
    parser.add_argument("--nuevo", action="store_true", help="borra la base y la crea solo con datos reales")
    args = parser.parse_args(argv)

    captures = latest_captures(args.probe_out)
    if not captures:
        sys.exit(f"No encontre capturas en {args.probe_out} (busco carpetas www.<tienda>_cat_*/productos.csv).")
    for store, path in captures.items():
        print(f"Captura de {store}: {path.parent.name}")

    rows, skipped = read_rows(captures)
    groups, refused_unions = cluster_rows(rows)
    print(f"\nListados importables: {len(rows)} | omitidos: {dict(skipped) or 'ninguno'}")
    print(f"Modelos distintos: {len(groups)} | uniones rechazadas: por marca {refused_unions['marca']}, "
          f"por tamano de pantalla {refused_unions['tamano']}")

    app = create_app()
    with app.app_context():
        if args.nuevo:
            db.drop_all()
        db.create_all()
        if not User.query.filter_by(email="demo@vigia.pe").first():
            demo = User(name="Usuario Demo", email="demo@vigia.pe")
            demo.set_password("demo1234")
            db.session.add(demo)

        category = Category.query.filter_by(code=CATEGORY_NAME).first() or Category(code=CATEGORY_NAME)
        db.session.add(category)
        retails = {}
        for store in captures:
            code = retail_code(store)
            retail = Retail.query.filter_by(code=code).first() or Retail(code=code, color=RETAIL_COLORS.get(code, "#6b7280"))
            db.session.add(retail)
            retails[store] = retail
        db.session.flush()

        brands = {}
        multi_store = over_merged = brand_conflicts = 0
        entries = 0
        for members in groups:
            code = canonical_code(members)
            brand_name = (Counter((m.get("marca") or "").strip().upper() for m in members).most_common(1)[0][0]
                          or "SIN MARCA")
            brand = brands.get(brand_name) or Brand.query.filter_by(code=brand_name).first() or Brand(code=brand_name)
            db.session.add(brand)
            brands[brand_name] = brand
            db.session.flush()
            if category not in brand.category_ids:
                brand.category_ids.append(category)

            if len({m["_store"] for m in members}) > 1:
                multi_store += 1
            attr_models = {norm_model(m.get("modelo")) for m in members if usable_model(norm_model(m.get("modelo")))}
            distinct_brands = sorted({brand_key(m) for m in members if brand_key(m)})
            if any(not brands_compatible(x, y) for i, x in enumerate(distinct_brands) for y in distinct_brands[i + 1:]):
                brand_conflicts += 1
                if brand_conflicts <= 5:
                    print(f"  AVISO: modelo {code} reune marcas incompatibles: {distinct_brands} (posible cruce falso)")
            shortest = min(attr_models, key=len) if attr_models else ""
            if len(attr_models) > 1 and any(not model.startswith(shortest) for model in attr_models):
                over_merged += 1
                print(f"  AVISO: modelo {code} reune atributos distintos: {sorted(attr_models)[:3]}")

            for m in members:
                retail = retails[m["_store"]]
                if retail not in brand.retail_ids:
                    brand.retail_ids.append(retail)
                available = {"True": True, "False": False}.get(str(m.get("disponible")))
                db.session.add(PriceEntry(
                    date=m["_date"], category_id=category.id, retail_id=retail.id, brand_id=brand.id,
                    product_code=code, min_price=m["_price"],
                    list_price=(parse_price(m.get("precio_lista")) or None),
                    card_price=(parse_price(m.get("precio_tarjeta")) or None),
                    is_available=available, seller=(m.get("vendedor") or None),
                    listing_ref=str(m.get("product_id") or "") or None,
                    name=(m.get("nombre") or None),
                    ean=(m["ean"] if m.get("ean") and valid_ean(m["ean"]) else None),
                ))
                entries += 1
        db.session.commit()

    per_store = Counter(m["_store"] for g in groups for m in g)
    print(f"\nGuardados {entries} listados: " + ", ".join(f"{s}: {n}" for s, n in per_store.items()))
    print(f"Modelos presentes en mas de una tienda: {multi_store}")
    if brand_conflicts:
        print(f"Modelos que reunen marcas incompatibles: {brand_conflicts} (posibles cruces falsos, revisa los AVISO)")
    if over_merged:
        print(f"Modelos con posible union de productos distintos: {over_merged} (revisa los AVISO de arriba)")
    print("\nListo. Abre el dashboard (python app.py), entra a /top y elige la categoria TELEVISORES.")


if __name__ == "__main__":
    main()
