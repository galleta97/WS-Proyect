"""
seed_inventory.py - crea las tablas de inventario y carga datos DEMO para el
dashboard y el kardex, sin tocar los precios capturados.

Qué hace:
  1. Respalda la base SQLite (precios.backup-inventario-<fecha>.db).
  2. Crea solo las tablas nuevas (products, suppliers, stock_movements,
     stock_alerts); las existentes no se modifican.
  3. Registra N productos como el catálogo de una ferretería piloto:
     - modo "ferreteria" (por defecto): productos de las categorías de
       ferretería cargadas con cargar_ferreteria.py que tengan precio en al
       menos 2 tiendas. Promart, Sodimac y las demás son los COMPETIDORES;
       el precio propio es un precio de ferretería simulado (entre 7 % por
       debajo y 10 % por encima del competidor más barato) y el costo, el 72 %.
     - modo "tv": la demo anterior con televisores, donde Promart hace de
       precio propio.
  4. Simula 30 días de entradas, salidas y ajustes con proveedores ficticios,
     para que el dashboard tenga rotación, alertas y movimientos del día.

Los proveedores, el precio propio y los movimientos son ficticios; sirven solo
para la demo. Los precios de la competencia son los capturados.

Uso:
  python seed_inventory.py                 # 60 productos de ferretería si no hay inventario
  python seed_inventory.py --reset         # borra SOLO los datos de inventario y recarga
  python seed_inventory.py --n 80 --reset  # otra cantidad
  python seed_inventory.py --modo tv --reset
"""

import argparse
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app
from extensions import db
from inventory import latest_competitor_prices, register_movement
from models import Category, PriceEntry, Product, Retail, StockAlert, StockMovement, Supplier, User
from routes.api import REFERENCE_RETAIL_CODE

SUPPLIERS = [
    ("20999999901", "Distribuidora Andina S.A.C."),
    ("20999999902", "Importaciones del Pacífico S.A.C."),
    ("20999999903", "Electro Mayorista Lima E.I.R.L."),
]
SALE_REASONS = ["Venta mostrador", "Venta mostrador", "Venta mostrador", "Venta web", "Venta corporativa"]


def backup_sqlite(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    path = Path(uri.replace("sqlite:///", "", 1))
    if not path.exists():
        return None
    dest = path.with_name(f"{path.stem}.backup-inventario-{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
    shutil.copy2(path, dest)
    return dest


def pick_models(n):
    """Modo tv: Promart es el precio propio y debe haber otras 2 tiendas."""
    ref = Retail.query.filter_by(code=REFERENCE_RETAIL_CODE).first()
    if ref is None:
        sys.exit(f"No existe la tienda de referencia {REFERENCE_RETAIL_CODE}.")
    tv = Category.query.filter_by(code="TELEVISORES").first()
    q = db.session.query(PriceEntry.product_code).filter(PriceEntry.retail_id == ref.id)
    if tv:
        q = q.filter(PriceEntry.category_id == tv.id)
    codes = [c for (c,) in q.distinct()]
    prices = latest_competitor_prices(codes)
    picked = []
    for code in sorted(codes):
        stores = prices.get(code, {})
        own = stores.get(REFERENCE_RETAIL_CODE)
        others = [v for rc, v in stores.items() if rc != REFERENCE_RETAIL_CODE and v["inStock"]]
        if own and own["inStock"] and len(others) >= 2:
            picked.append((code, own["price"]))
    rng = random.Random(7)
    rng.shuffle(picked)
    return picked[:n]


def pick_hardware(n, rng):
    """Modo ferretería: productos fuera de TELEVISORES con precio en 2 o más
    tiendas. El precio propio se simula frente al competidor más barato."""
    tv = Category.query.filter_by(code="TELEVISORES").first()
    q = db.session.query(PriceEntry.product_code)
    if tv:
        q = q.filter(PriceEntry.category_id != tv.id)
    codes = [c for (c,) in q.distinct()]
    prices = latest_competitor_prices(codes)
    picked = []
    for code in sorted(codes):
        in_stock = [v["price"] for v in prices.get(code, {}).values() if v["inStock"]]
        if len(in_stock) >= 2:
            cheapest = min(in_stock)
            own = round(cheapest * rng.uniform(0.93, 1.10)) - 0.10
            picked.append((code, max(own, 0.9)))
    rng.shuffle(picked)
    return picked[:n]


def product_name(code):
    """Nombre del producto, preferentemente como lo publica Promart."""
    ref = Retail.query.filter_by(code=REFERENCE_RETAIL_CODE).first()
    q = PriceEntry.query.filter_by(product_code=code).filter(PriceEntry.name.isnot(None))
    row = None
    if ref:
        row = q.filter(PriceEntry.retail_id == ref.id).order_by(PriceEntry.date.desc()).first()
    row = row or q.order_by(PriceEntry.date.desc()).first()
    return (row.name if row else code)[:200], row


def simulate(product, user_id, suppliers, rng, start, now, popularity):
    """30 días de movimientos para un producto."""
    def at(day, hour, minute):
        return start + timedelta(days=day, hours=hour, minutes=minute)

    initial = rng.randint(12, 35)
    register_movement(product.id, "AJUSTE", initial, user_id,
                      reason="Inventario inicial", when=at(0, 8, 0), commit=False)
    guide = rng.randint(4000, 4900)
    days = (now - start).days
    for day in range(days + 1):
        # Cada día en orden cronológico: reposición a primera hora, ventas
        # entre las 9 y las 19 y, rara vez, una merma al cierre.
        # La reposición llega cuando el stock está en el mínimo (no siempre a tiempo).
        when = at(day, 8, 30)
        if day and product.stock <= product.min_stock and rng.random() < 0.45 and when < now - timedelta(days=2):
            guide += 1
            register_movement(product.id, "ENTRADA", rng.randint(12, 30), user_id,
                              supplier_id=rng.choice(suppliers).id,
                              reason=f"T001-{guide:06d}", when=when, commit=False)
        hours = sorted(rng.sample(range(9, 20), 4))
        for hour in hours:
            when = at(day, hour, rng.randint(0, 59))
            if when >= now:
                break
            if rng.random() < popularity:
                qty = min(product.stock, rng.choice([1, 1, 1, 2, 2, 3]))
                if qty > 0:
                    register_movement(product.id, "SALIDA", qty, user_id,
                                      reason=rng.choice(SALE_REASONS), when=when, commit=False)
        when = at(day, 20, 15)
        if rng.random() < 0.02 and product.stock > 0 and when < now:
            register_movement(product.id, "AJUSTE", -1, user_id,
                              reason="Producto dañado", when=when, commit=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=60, help="cantidad de productos (por defecto 60)")
    parser.add_argument("--modo", choices=("ferreteria", "tv"), default="ferreteria",
                        help="catálogo demo: ferretería (por defecto) o televisores")
    parser.add_argument("--reset", action="store_true", help="borra los datos de inventario antes de cargar")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        has_products = (db.inspect(db.engine).has_table(Product.__tablename__)
                        and Product.query.count() > 0)
        if has_products and not args.reset:
            print("Ya hay productos de inventario. Usa --reset para recargar los datos demo.")
            return

        backup = backup_sqlite(app)
        if backup:
            print(f"Respaldo: {backup.name}")
        db.create_all()  # solo crea las tablas que faltan
        if args.reset:
            for model in (StockAlert, StockMovement, Product, Supplier):
                model.query.delete()
            db.session.commit()

        user = User.query.filter_by(email="demo@vigia.pe").first() or User.query.first()
        if user is None:
            sys.exit("No hay usuarios. Crea una cuenta o ejecuta seed.py primero.")

        rng = random.Random(42)
        if args.modo == "tv":
            models, prefix, cost_ratio, mins = pick_models(args.n), "TV", 0.82, [3, 4, 5, 6, 8, 10]
        else:
            models, prefix, cost_ratio, mins = pick_hardware(args.n, rng), "FER", 0.72, [5, 6, 8, 10, 12, 15]
        if not models:
            hint = ("Carga primero los productos de ferretería con cargar_ferreteria.py."
                    if args.modo == "ferreteria" else "No hay televisores con precio en Promart y otras dos tiendas.")
            sys.exit("No hay productos para el inventario demo. " + hint)

        suppliers = [Supplier(ruc=r, business_name=name) for r, name in SUPPLIERS]
        db.session.add_all(suppliers)
        db.session.flush()

        now = datetime.now().replace(second=0, microsecond=0)
        start = (now - timedelta(days=30)).replace(hour=0, minute=0)
        for i, (code, price) in enumerate(models, start=1):
            name, row = product_name(code)
            product = Product(
                code=f"{prefix}-{i:04d}",
                name=name,
                category_id=row.category_id if row else 1,
                unit="unidad",
                cost=round(price * cost_ratio, 2),
                sale_price=round(price, 2),
                stock=0,
                min_stock=rng.choice(mins),
                price_code=code,
            )
            db.session.add(product)
            db.session.flush()
            simulate(product, user.id, suppliers, rng, start, now, popularity=rng.uniform(0.05, 0.55))
        db.session.commit()

        low = sum(1 for p in Product.query.all() if p.min_stock and p.stock <= p.min_stock)
        print(f"Productos: {len(models)} · movimientos: {StockMovement.query.count()} · "
              f"alertas abiertas: {StockAlert.query.filter_by(status='ABIERTA').count()} · "
              f"en o bajo el mínimo: {low}")


if __name__ == "__main__":
    main()
