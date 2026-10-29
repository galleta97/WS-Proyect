"""
Genera datos de ejemplo para poder correr el dashboard de inmediato.

Uso:
    python seed.py

Esto crea precios.db desde cero (si ya existe, la reemplaza) con un set
pequeño de categorías/marcas/retailers/importaciones/precios de ejemplo,
suficiente para ver las tablas y filtros funcionando end-to-end.

Cuando conectes tus scrapers reales (ej. scrapers/vtex_stores.py), esos
procesos deben insertar filas en ImportRecord / WebHomePrice / PriceEntry
siguiendo la misma estructura que ves aquí.
"""

import os
import random
from datetime import date, timedelta

from app import create_app
from extensions import db
from models import (
    Brand,
    Category,
    Feature,
    ImportRecord,
    Importer,
    MktEvent,
    PriceEntry,
    Retail,
    User,
    WebHome,
    WebHomePrice,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "precios.db")


def seed():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    app = create_app()
    with app.app_context():
        db.create_all()

        # --- Usuario de prueba para poder loguearte de inmediato ---
        demo_user = User(name="Usuario Demo", email="demo@vigia.pe")
        demo_user.set_password("demo1234")
        db.session.add(demo_user)

        # --- Categorías ---
        cat_tv = Category(code="TV LED")
        cat_cel = Category(code="CELULARES")
        cat_lav = Category(code="LAVADORAS")
        db.session.add_all([cat_tv, cat_cel, cat_lav])
        db.session.flush()

        # --- Retailers ---
        retails = {
            # Colores vivos y distinguibles — se usan tanto en las
            # insignias de la tabla como en las líneas de los gráficos, así
            # que deben tener buen contraste sobre fondo blanco (nada de
            # tonos pastel, se ven "lavados" en Chart.js).
            "PROMART": Retail(code="PROMART", color="#f97316"),
            "SODIMAC": Retail(code="SODIMAC", color="#e11d48"),
            "FALABELLA": Retail(code="FALABELLA", color="#22c55e"),
            "PLAZAVEA": Retail(code="PLAZAVEA", color="#eab308"),
            "TOTTUS": Retail(code="TOTTUS", color="#0ea5e9"),
        }
        db.session.add_all(retails.values())
        db.session.flush()

        # --- Marcas ---
        brands = {
            "SAMSUNG": Brand(code="SAMSUNG"),
            "LG": Brand(code="LG"),
            "TCL": Brand(code="TCL"),
            "HISENSE": Brand(code="HISENSE"),
        }
        for b in brands.values():
            b.category_ids = [cat_tv]
            b.retail_ids = list(retails.values())
        db.session.add_all(brands.values())
        db.session.flush()

        # --- Importadoras ---
        importers = {
            "SAMSUNG ELECTRONICS PERU SAC": Importer(code="SAMSUNG ELECTRONICS PERU SAC"),
            "LG ELECTRONICS PERU S.A.": Importer(code="LG ELECTRONICS PERU S.A."),
            "TCL ELECTRONICS PERU S.A.C.": Importer(code="TCL ELECTRONICS PERU S.A.C."),
        }
        db.session.add_all(importers.values())
        db.session.flush()

        # --- Features ---
        db.session.add_all([
            Feature(code="32", category_id=cat_tv.id),
            Feature(code="55", category_id=cat_tv.id),
            Feature(code="65", category_id=cat_tv.id),
            Feature(code="75", category_id=cat_tv.id),
        ])

        # --- Eventos de marketing ---
        db.session.add_all([
            MktEvent(code="CyberWow - Abril", from_date=date(2026, 4, 7), to_date=date(2026, 4, 10), year=2026),
            MktEvent(code="Día de la madre", from_date=date(2026, 4, 28), to_date=date(2026, 5, 11), year=2026),
            MktEvent(code="Black Friday", from_date=date(2026, 11, 28), to_date=date(2026, 11, 28), year=2026),
        ])

        # --- Importaciones de ejemplo ---
        products_tv = ["UN65M80HAGXPE", "50C6KS", "85UR8SG", "OLED77G3PSA", "QN55Q80AAG"]
        today = date.today()
        for i in range(60):
            brand = random.choice(list(brands.values()))
            db.session.add(ImportRecord(
                date=today - timedelta(days=random.randint(0, 30)),
                category_id=cat_tv.id,
                brand_id=brand.id,
                product_code=random.choice(products_tv),
                importer_id=random.choice(list(importers.values())).id,
                description=f"TELEVISOR, {brand.code}, USO COMERCIAL",
                cost=round(random.uniform(90, 1500), 2),
                quantity=random.randint(1, 500),
                aduana_code=f"{random.randint(400000, 406999)} | {random.randint(1, 10)}",
                feature1=random.choice(["32", "55", "65", "75"]),
                feature2="Mayor a 50'",
                origin="TELEVISOR",
            ))

        # --- Web Homes (páginas monitoreadas) ---
        db.session.add_all([
            WebHome(country="PE", retail_id=retails["FALABELLA"].id, url="https://www.falabella.com.pe/falabella-pe"),
            WebHome(country="PE", retail_id=retails["PLAZAVEA"].id, url="https://www.plazavea.com.pe/"),
            WebHome(country="PE", retail_id=retails["PROMART"].id, url="https://www.promart.pe/"),
        ])

        # --- Precios de Web Homes de ejemplo ---
        for i in range(40):
            brand = random.choice(list(brands.values()))
            retail = random.choice(list(retails.values()))
            normal = round(random.uniform(800, 3500), 2)
            offer = round(normal * random.uniform(0.7, 0.95), 2)
            db.session.add(WebHomePrice(
                date=today - timedelta(days=random.randint(0, 10)),
                retail_id=retail.id,
                brand_id=brand.id,
                product=random.choice(products_tv),
                actual=offer,
                offer=offer,
                normal=normal,
                discounts=f"{round((1 - offer / normal) * 100)}%",
                description=f"{brand.code} Smart TV",
            ))

        # --- Price entries (para /prices/matrix — Search y Top Sales, y
        # /prices/history para el generador de gráficos). Generamos 14 días
        # de histórico por producto/tienda para que el "Price Tracking" y
        # los gráficos de torta/barras tengan datos reales que mostrar.
        # Ciclamos las marcas en vez de elegir al azar, para garantizar que
        # las 4 queden representadas en al menos un producto (con solo 5
        # productos de ejemplo, random.choice() podía dejar alguna marca
        # sin ningún producto y romper filtros de demo por marca).
        brand_cycle = list(brands.values())
        product_brand = {p: brand_cycle[i % len(brand_cycle)] for i, p in enumerate(products_tv)}
        product_base_price = {p: round(random.uniform(800, 3500), 2) for p in products_tv}

        for product in products_tv:
            brand = product_brand[product]
            base = product_base_price[product]
            # cada producto solo se vende en un subconjunto de tiendas
            # Cada producto disponible en TODAS las tiendas (más realista y
            # evita que combinaciones de filtro razonables den "No data" en
            # la demo por simple mala suerte del muestreo aleatorio).
            product_retails = list(retails.values())
            for retail in product_retails:
                retail_offset = random.uniform(0.85, 1.15)  # cada tienda tiene su propio nivel de precio
                # Estado de stock de esa tienda para este producto: casi
                # siempre disponible, con ~8% de probabilidad de arrancar
                # agotado, para tener algo de variedad en la demo desde el
                # día 1 (Fase 4).
                available = random.random() > 0.08
                # Vendedor dentro de esa tienda: casi siempre la propia tienda,
                # pero en las tiendas con marketplace (Promart, Falabella,
                # Sodimac) una parte de los productos los publica un tercero.
                third_party_rate = {"PROMART": 0.4, "FALABELLA": 0.3, "SODIMAC": 0.3}.get(retail.code, 0)
                if random.random() < third_party_rate:
                    seller_name = random.choice(["Carsa", "Oechsle", "Hiraoka", "Distribuidor Autorizado"])
                else:
                    seller_name = retail.code.title()
                for day_offset in range(14, -1, -1):
                    day = today - timedelta(days=day_offset)
                    drift = random.uniform(-0.03, 0.03)  # variación diaria pequeña
                    price = round(base * retail_offset * (1 + drift), 2)
                    # Pequeña probabilidad de que el stock cambie de un día
                    # a otro, para tener algo de historial de cambios.
                    if random.random() < 0.05:
                        available = not available
                    db.session.add(PriceEntry(
                        date=day,
                        category_id=cat_tv.id,
                        retail_id=retail.id,
                        brand_id=brand.id,
                        product_code=product,
                        min_price=price,
                        has_sales_rank=random.random() < 0.5,
                        sales_rank=random.randint(1, 50),
                        is_available=available,
                        seller=seller_name,
                    ))

        db.session.commit()
        print("✅ precios.db creada con datos de ejemplo.")
        print("   Usuario de prueba -> correo: demo@vigia.pe / contraseña: demo1234")


if __name__ == "__main__":
    seed()
