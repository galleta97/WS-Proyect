"""
Utilidades para importar capturas reales de precios (las mismas reglas que usa
probe_stores.py / clase3.py, copiadas aqui para que el proyecto no dependa de
ese archivo).
"""

import re

# Accesorios: se reconocen por como EMPIEZA el nombre. Excluir por palabras
# sueltas ("control", "base") descartaba televisores reales.
ACCESSORY_START = re.compile(
    r"^\s*(rack|soporte|base|soundbar|sound bar|barra|antena|control|cable|proyector|bocina|parlante|"
    r"mueble|kit|funda|cubierta|limpiador|cargador|adaptador|extension|extensi\u00f3n|protector)\b",
    re.I,
)
# Paquetes: el televisor viene con otro producto (+ Rack, - Antena, mas Soundbar...) y su precio no es comparable
BUNDLE = re.compile(r"(?:\+|\bmas\b|\s-\s)\s*(?:rack|antena|soporte|base|soundbar|barra|parlante|kit)", re.I)
STRONG_NON_TV = re.compile(r"parlantes?|bocinas?|soundbar|barra de sonido|aud[i\u00ed]fonos?|streaming device|chromecast", re.I)
TV_WORDS = re.compile(r"televisor|smart ?tv|\btv\b|qled|oled|mini ?led|nanocell", re.I)
# "LED" solo no basta (lamparas, paneles, reflectores): hace falta ademas una medida en pulgadas
LED_WORD = re.compile(r"\bled\b", re.I)
INCH_SIZE = re.compile(r"\b\d{2,3}\s?(?:\"|''|\u201d|pulgadas|pulg\.?|pg\b)", re.I)

# Especificaciones que parecen codigos pero no identifican un modelo: 144HZ, 1920X1080, 2026
GENERIC_TOKEN = re.compile(r"^(\d+(HZ|NITS|GB|TB|W|CM|MM|K|P)|\d+X\d+|\d{4})$")


def is_tv(name):
    name = name or ""
    looks_tv = bool(TV_WORDS.search(name)) or (bool(LED_WORD.search(name)) and bool(INCH_SIZE.search(name)))
    return (looks_tv and not ACCESSORY_START.search(name) and not STRONG_NON_TV.search(name)
            and not BUNDLE.search(name))


def valid_ean(code):
    """EAN-13 real: 13 digitos, digito verificador correcto y sin prefijo 2 (uso interno de tienda)."""
    digits = re.sub(r"\D", "", str(code or ""))
    if len(digits) != 13 or digits.startswith("2"):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def norm_model(value):
    """Modelo comparable entre tiendas: mayusculas, sin espacios ni signos."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def usable_model(key):
    """Un modelo sirve para cruzar si es especifico: 5+ caracteres con letras y numeros."""
    return len(key) >= 5 and any(c.isdigit() for c in key) and any(c.isalpha() for c in key)


def model_tokens(*texts):
    """Codigos tipo modelo que aparecen en nombres o atributos (sin especificaciones genericas).
    Tambien se prueba el codigo sin sufijo tras punto o barra (65NU800BPSB.AWFQ -> 65NU800BPSB),
    pero NO se parte por guion: BL32-T3000QD y BL43-T3000QD son modelos distintos."""
    out = set()
    for text in texts:
        for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]{3,}", str(text or "")):
            for part in [tok] + re.split(r"\.+", tok):
                t = re.sub(r"[^A-Z0-9]", "", part.upper())
                if usable_model(t) and not GENERIC_TOKEN.match(t):
                    out.add(t)
    return out


def parse_price(value):
    """'S/ 1,299.90', '1299,90', 1299 -> float. None si no se puede."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("S/", "").replace("s/", "").replace("\xa0", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + ("." + tail if len(tail) == 2 else tail)
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Agrupar listados en modelos (con compuerta de marca)
# ---------------------------------------------------------------------------

# Marcas "comodin": no identifican al fabricante, asi que no pueden unir marcas distintas
WILD_BRANDS = {"", "GENERICO", "GENÉRICO", "SIN MARCA", "OTRA", "OTRAS", "OTROS", "N/A", "NA"}


def brand_key(row):
    """Marca normalizada, o '' si es un comodin (generico, sin marca...)."""
    b = re.sub(r"\s+", " ", str(row.get("marca") or "").strip().upper())
    return "" if b in WILD_BRANDS else b


def brands_compatible(a, b):
    """HYUNDAI y HYUNDAI TECHNOLOGY son la misma marca; LG y SAMSUNG no."""
    return a == b or a.startswith(b) or b.startswith(a)


def row_keys(row):
    """Claves que identifican un modelo: EAN valido y codigos de modelo (atributo o nombre)."""
    keys = set()
    if row.get("ean") and valid_ean(row["ean"]):
        keys.add("E:" + row["ean"])
    model = norm_model(row.get("modelo"))
    if usable_model(model):
        keys.add("M:" + model)
    for token in model_tokens(row.get("nombre")):
        keys.add("M:" + token)
    return keys


# Tamanos de pantalla (pulgadas) que existen como televisores
TV_SIZES = {24, 28, 32, 40, 42, 43, 46, 48, 49, 50, 52, 55, 58, 60, 65, 70, 75, 77, 82, 83, 85, 86, 98, 100}
# numero suelto (no parte de un codigo ni de "120Hz"), con o sin comillas/pulgadas
STANDALONE_NUM = re.compile(
    r"(?<![A-Za-z0-9.,])(\d{2,3})(?:\s?(?:\"|''|\u00b4\u00b4|\u201d|pulgadas|pulg\.?))?(?![A-Za-z0-9])(?!\s?hz)", re.I)
# prefijo de tamano dentro de un codigo de modelo: UN55U8000, 55QNED65, LT50KM758, L55MB, C32K4HG
CODE_SIZE = re.compile(r"^[A-Z]{0,3}(\d{2,3})[A-Z]")


def tv_size(row):
    """Pulgadas del televisor leidas del nombre o de su codigo; None si no se puede saber."""
    name = str(row.get("nombre") or "")
    for m in STANDALONE_NUM.finditer(name):
        if int(m.group(1)) in TV_SIZES:
            return int(m.group(1))
    for tok in sorted(model_tokens(name) | {norm_model(row.get("modelo"))}):
        m = CODE_SIZE.match(tok)
        if m and int(m.group(1)) in TV_SIZES:
            return int(m.group(1))
    return None


def cluster_rows(rows):
    """Une listados que comparten EAN valido o codigo de modelo, pero NUNCA une grupos de marcas
    incompatibles ni de tamanos de pantalla distintos (un 32" y un 85" no son comparables).
    Devuelve (grupos, uniones_rechazadas) con las rechazadas por marca y por tamano."""
    parent = list(range(len(rows)))
    group_brand = [brand_key(r) for r in rows]
    group_size = [tv_size(r) for r in rows]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners, refused = {}, {"marca": 0, "tamano": 0}
    for i, row in enumerate(rows):
        for key in row_keys(row):
            reps = owners.setdefault(key, [])
            for rep in reps:
                ra, rb = find(rep), find(i)
                if ra == rb:
                    break
                ba, bb = group_brand[ra], group_brand[rb]
                if ba and bb and not brands_compatible(ba, bb):
                    refused["marca"] += 1
                    continue
                sa, sb = group_size[ra], group_size[rb]
                if sa and sb and sa != sb:
                    refused["tamano"] += 1
                    continue
                parent[rb] = ra
                if not ba:
                    group_brand[ra] = bb
                if not sa:
                    group_size[ra] = sb
                break
            else:
                reps.append(i)
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    return list(groups.values()), refused
