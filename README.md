# Pricing Intelligence Dashboard

Dashboard propio de monitoreo de precios (categorías, marcas, retailers,
importaciones aduaneras, precios extraídos de home pages, y búsqueda de
precios con vista "Top Sales"). La lógica de filtros/paginación replica el
patrón que mapeamos de la plataforma de referencia, pero con tu propio
stack y tus propios datos.

## Estructura

```
pricing_dashboard/
  app.py              <- app factory + arranque
  config.py           <- configuración (ruta de la DB SQLite)
  extensions.py       <- instancia de SQLAlchemy
  models.py           <- todas las tablas
  seed.py             <- datos de ejemplo para probar de inmediato
  routes/
    api.py            <- endpoints JSON (/api/...)
    views.py          <- páginas Jinja2 (/top, /imports, /web-homes)
  templates/           <- HTML (Jinja2)
  static/css/style.css
  static/js/           <- lógica de filtros/tablas por página
```

## Instalación y arranque

```bash
pip install -r requirements.txt
python seed.py       # crea precios.db con datos de ejemplo + usuario de prueba
python app.py         # http://127.0.0.1:5000
```

Abre `http://127.0.0.1:5000/` — esa es ahora la landing page pública. Desde
ahí puedes "Crear cuenta" o iniciar sesión con el usuario de prueba que
genera `seed.py`:

```
correo:      demo@vigia.pe
contraseña:  demo1234
```

Las páginas `/top`, `/imports` y `/web-homes` ahora requieren sesión
iniciada — si intentas entrar sin loguearte, te redirige a `/login`.

## Cargar datos REALES (capturas de Promart, Metro, etc.)

Las capturas se hacen con `clase3.py` / `probe_stores.py` (carpeta `probe_out`).
Para verlas en el dashboard:

```
python import_capture.py --probe-out C:\ruta\a\probe_out --nuevo
python app.py
```

- Toma la captura mas reciente de cada tienda (carpetas `www.<tienda>_cat_*`).
- Une los listados de distintas tiendas en un mismo modelo por EAN valido o
  codigo de modelo (en el atributo o dentro del nombre).
- Cuando una tienda tiene varios listados del mismo modelo, el dashboard muestra
  el mas barato con stock (el tooltip dice cuantos listados hay y quien vende).
- `--nuevo` BORRA la base actual, datos de ejemplo incluidos. Sin esa opcion
  agrega a lo que ya existe.
- Con datos reales, deja `ENABLE_PRICE_WATCHER=false` en `.env`: ese hilo
  inventa variaciones de precio solo para la demo.

## Seguridad — antes de desplegar esto en producción

Esta autenticación es funcional para desarrollo, pero le faltan capas
típicas de un sistema en producción:

- **`SECRET_KEY`**: en `config.py` hay una clave de desarrollo hardcodeada.
  Antes de desplegar, cámbiala por una variable de entorno real
  (`SECRET_KEY=algo-largo-y-aleatorio`), nunca la subas a un repositorio.
- **Sin protección CSRF** en los formularios de login/registro — para
  producción, agrega Flask-WTF o similar.
- **Sin límite de intentos de login** (rate limiting) — alguien podría
  probar contraseñas repetidamente. Considera Flask-Limiter.
- **Sin verificación de correo** ni recuperación de contraseña — hoy
  cualquier correo se acepta tal cual al registrarse.
- **HTTPS obligatorio** en producción — las cookies de sesión no deben
  viajar sin cifrar.

## Endpoints disponibles

**Catálogos compartidos**
- `GET /api/categories/`
- `GET /api/retails/`
- `GET /api/brands/?categoryIds[]=X`
- `GET /api/features/?categoryIds[]=X`
- `GET /api/mkt-event/`

**Imports**
- `GET /api/categories/imports`
- `GET /api/imports/brands?categoryIds[]=X`
- `GET /api/imports/importers?categoryIds[]=X`
- `GET /api/imports/products?categoryIds[]=X`
- `GET /api/retails/imports`
- `GET /api/imports/?page=1&size=50&categoryIds[]=X&brandIds[]=Y&fromDate=YYYY-MM-DD`

**Web Homes**
- `GET /api/web-home/homes`
- `GET /api/web-home/brands`
- `GET /api/web-home/image-alts`
- `GET /api/web-home/prices?page=1&size=20&fromDate=X&toDate=Y&retailIds[]=Z`

**Precios / Top Sales**
- `GET /api/prices/matrix?categoryIds[]=X&retailIds[]=Y&brandIds[]=Z` → modo
  Search: 1 fila = 1 producto, con el precio mínimo de cada tienda donde
  exista match exacto (esto resuelve el problema que tenías con la tabla
  "Modes": no mezcla productos distintos en la misma fila).
- Agrega `&hasSalesRank=true&categoryId=X` → modo Top Sales, ordenado por
  ranking de ventas.

## Conectar tus scrapers reales

Ahora mismo `seed.py` genera datos de ejemplo aleatorios. Para producción,
tus procesos de scraping (ej. `scrapers/vtex_stores.py` de tu proyecto
actual) deben insertar filas directamente en los modelos:

- Cada producto/precio de importación → `ImportRecord`
- Cada precio extraído de un home page → `WebHomePrice`
- Cada precio de un producto en una tienda (para Search / Top Sales) →
  `PriceEntry` — aquí es donde se resuelve el match "1 producto = 1 fila":
  usa el mismo `product_code` para el mismo producto en todas las tiendas.

Ejemplo mínimo desde un scraper:

```python
from app import create_app
from extensions import db
from models import PriceEntry, Category, Retail, Brand
from datetime import date

app = create_app()
with app.app_context():
    db.session.add(PriceEntry(
        date=date.today(),
        category_id=1,
        retail_id=1,
        brand_id=1,
        product_code="UN65M80HAGXPE",
        min_price=1899.90,
        has_sales_rank=False,
    ))
    db.session.commit()
```

## Integrar con tu proyecto Flask actual

Si ya tienes un `app.py` con Flask 3 + Flask-SQLAlchemy sobre `precios.db`:

1. Copia `models.py` (o fusiona sus tablas con las que ya tengas).
2. Copia `routes/api.py` y regístralo como blueprint en tu `app.py`
   existente: `app.register_blueprint(api_bp)`.
3. Copia los templates y archivos estáticos, o adáptalos a tu CSS actual.
4. Corre `flask shell` o un script de migración para crear las tablas
   nuevas (`db.create_all()`), sin necesidad de borrar tu `precios.db`
   existente — SQLAlchemy solo crea las tablas que faltan.

## Próximos pasos sugeridos

- Agregar autenticación (login) si vas a tener múltiples usuarios/clientes.
- Agregar exportación a Excel/PDF en `/api/imports/` y `/api/web-home/prices`
  reutilizando jsPDF/SheetJS como ya haces en tu dashboard actual.
- Migrar de SQLite a Postgres cuando el volumen de datos crezca (el patrón
  de queries ya está escrito con SQLAlchemy, así que el cambio es
  principalmente de configuración).
