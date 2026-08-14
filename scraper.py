"""
Scraper de cortes de energía - Colombia
-----------------------------------------
Corre cada hora vía GitHub Actions. Por cada operador:
  1. Busca noticias recientes en Google News RSS (sin API key, sin auth).
  2. Extrae texto del artículo.
  3. Con reglas de texto (regex) intenta identificar: barrios/sectores,
     circuito, subestación, horario.
  4. Geocodifica a nivel de ciudad/municipio (diccionario estático, o
     Google Geocoding API si GOOGLE_MAPS_API_KEY está configurada).
  5. Envía el resultado al Apps Script:
       - 'saveCortes'         -> reemplaza el estado "activo" del mapa
       - 'actualizarBiblioteca' -> agrega/actualiza el catálogo histórico
         de subestaciones/circuitos (solo si se detectó circuito o
         subestación explícitos en el texto)

LIMITACIÓN HONESTA: la extracción es por texto (regex), no NLP real.
Funciona bien cuando el operador redacta de forma consistente (Afinia,
Air-e sí publican "Circuito X", "Subestación Y"); para comunicados más
libres (Enel, EPM) probablemente solo capture barrios y ciudad, dejando
circuito/subestación como "N/D". Es un punto de partida para afinar
con el tiempo, no un extractor perfecto desde el día uno.
"""

import os
import re
import json
import time
import unicodedata
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

GAS_URL = os.environ.get("GAS_URL", "").strip()
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

if not GAS_URL:
    raise SystemExit("Falta la variable de entorno GAS_URL (URL /exec de tu Apps Script)")

# ── Operadores a monitorear y su región/coordenada base ─────────────
OPERADORES = [
    {"nombre": "Enel/Codensa", "queries": ["Enel cortes de luz", "Codensa cortes de luz", "cortes de luz Bogota"],
     "departamento": "Bogotá / Cundinamarca", "lat": 4.65, "lng": -74.10},
    {"nombre": "Afinia", "queries": ["Afinia cortes de luz", "Afinia trabajos programados", "cortes de luz Cartagena", "cortes de luz Monteria"],
     "departamento": "Bolívar / Cesar / Córdoba / Sucre", "lat": 9.30, "lng": -75.40},
    {"nombre": "Air-e", "queries": ["Air-e cortes de luz", "cortes de luz Barranquilla", "cortes de luz Riohacha", "cortes de luz Santa Marta"],
     "departamento": "Atlántico / Magdalena / La Guajira", "lat": 10.9, "lng": -74.8},
    {"nombre": "EPM", "queries": ["EPM cortes de energia", "EPM cortes de luz Antioquia"],
     "departamento": "Antioquia", "lat": 6.7, "lng": -75.3},
    {"nombre": "Celsia", "queries": ["Celsia cortes de energia", "cortes de luz Valle del Cauca", "cortes de luz Tolima"],
     "departamento": "Valle del Cauca / Tolima", "lat": 3.9, "lng": -76.3},
    {"nombre": "Emcali", "queries": ["Emcali cortes de luz", "cortes de luz Cali"],
     "departamento": "Valle del Cauca (Cali)", "lat": 3.45, "lng": -76.53},
    {"nombre": "CENS", "queries": ["CENS cortes de energia", "cortes de luz Cucuta"],
     "departamento": "Norte de Santander", "lat": 7.89, "lng": -72.5},
    {"nombre": "EBSA", "queries": ["EBSA cortes de energia", "cortes de luz Boyaca"],
     "departamento": "Boyacá", "lat": 5.45, "lng": -73.36},
]

# Ciudades conocidas -> coordenadas aproximadas (fallback sin API de geocoding)
CIUDADES_COORD = {
    "bogota": (4.65, -74.10), "soacha": (4.58, -74.22), "funza": (4.72, -74.21),
    "cota": (4.81, -74.10), "cartagena": (10.391, -75.479), "barranquilla": (10.968, -74.781),
    "riohacha": (11.544, -72.907), "uribia": (11.71, -72.27), "monteria": (8.75, -75.88),
    "valledupar": (10.47, -73.25), "sincelejo": (9.30, -75.40), "medellin": (6.25, -75.56),
    "rionegro": (6.15, -75.37), "cali": (3.45, -76.53), "ibague": (4.44, -75.23),
    "cucuta": (7.89, -72.50), "tunja": (5.54, -73.36), "magangue": (9.24, -74.75),
}


def normalizar(texto):
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    return t.strip().upper()


def geocodificar_ciudad(nombre_ciudad, fallback_lat, fallback_lng):
    clave = normalizar(nombre_ciudad).lower()
    for ciudad, coords in CIUDADES_COORD.items():
        if ciudad in clave or clave in ciudad:
            return coords
    if GOOGLE_MAPS_API_KEY:
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": f"{nombre_ciudad}, Colombia", "key": GOOGLE_MAPS_API_KEY},
                timeout=10,
            )
            data = r.json()
            if data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return (loc["lat"], loc["lng"])
        except Exception:
            pass
    return (fallback_lat, fallback_lng)


# ── Extracción de patrones del texto de la noticia ───────────────────
RE_CIRCUITO = re.compile(r"[Cc]ircuito[s]?\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]*(?:\s+\d+)?|\d+)")
RE_SUBESTACION = re.compile(r"[Ss]ubestaci[oó]n\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-Z]*(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]*)?)")
RE_HORARIO = re.compile(r"(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?)\s*[a-zA–—-]{1,3}\s*(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?)")
RE_BARRIOS = re.compile(r"[Bb]arrio[s]?\s*(?:afectados)?\s*:?\s*([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 ,]{3,150})")
RE_RESUELTO = re.compile(r"restablec|normaliz|solucion|se recuper|ya cuenta con el suministro|servicio.{0,15}restablecido", re.IGNORECASE)


def detectar_estado(texto, fin_str):
    """Heurística honesta: si el texto dice explícitamente que se
    restableció el servicio, o la hora de fin reportada ya pasó respecto
    a la hora actual en Colombia, se marca 'resuelto'. Si no hay
    evidencia de ninguna de las dos cosas, se asume 'activo' (más seguro
    para el usuario que asumir resuelto sin evidencia)."""
    if RE_RESUELTO.search(texto[:4000]):
        return "resuelto"
    m = re.match(r"(\d{1,2}):(\d{2})", fin_str or "")
    if m:
        try:
            ahora_co = datetime.now(timezone.utc) - timedelta(hours=5)
            hora_fin = ahora_co.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            es_pm = "p.m" in (fin_str or "").lower() or "pm" in (fin_str or "").lower()
            if es_pm and hora_fin.hour < 12:
                hora_fin = hora_fin.replace(hour=hora_fin.hour + 12)
            if ahora_co > hora_fin:
                return "resuelto"
        except Exception:
            pass
    return "activo"


def extraer_texto_articulo(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:8000]
    except Exception:
        return ""


def parsear_reporte(texto, titulo):
    circuito = "N/D"
    m = RE_CIRCUITO.search(texto) or RE_CIRCUITO.search(titulo)
    if m:
        circuito = "Circuito " + m.group(1).strip()

    subestacion = "N/D"
    m = RE_SUBESTACION.search(texto) or RE_SUBESTACION.search(titulo)
    if m:
        subestacion = "Subestación " + m.group(1).strip()

    inicio, fin = "—", "—"
    m = RE_HORARIO.search(texto)
    if m:
        inicio, fin = m.group(1).strip(), m.group(2).strip()

    barrios = []
    for m in RE_BARRIOS.finditer(texto[:3000]):
        partes = [p.strip(" .") for p in re.split(r",| y ", m.group(1)) if p.strip(" .")]
        barrios.extend(partes[:8])
    barrios = list(dict.fromkeys(barrios))[:15]

    return {
        "circuito": circuito, "subestacion": subestacion,
        "inicio": inicio, "fin": fin, "barrios": barrios,
    }


def buscar_noticias(query, horas_atras=24, max_items=6):
    q = requests.utils.quote(f"{query} Colombia")
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CO&ceid=CO:es-419"
    feed = feedparser.parse(url)
    limite = datetime.now(timezone.utc) - timedelta(hours=horas_atras)
    items = []
    for entry in feed.entries[:20]:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        if published >= limite:
            items.append({"title": entry.title, "link": entry.link, "published": published})
        if len(items) >= max_items:
            break
    return items


def gas_get(params, timeout=55, intentos=3):
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.get(GAS_URL, params=params, timeout=timeout)
            if not r.text.strip():
                raise ValueError("Respuesta vacía de Apps Script")
            return r.json()
        except Exception as e:
            ultimo_error = e
            print(f"  ! Intento {intento}/{intentos} fallo (getCortes): {e}")
            if intento < intentos:
                time.sleep(5 * intento)
    return {"ok": False, "error": str(ultimo_error)}


def clave_evento(ev):
    return (ev.get("operador", "").strip().lower(), ev.get("ciudad", "").strip().lower())


def reconciliar_por_fecha(eventos, hoy_str):
    """Antes de fusionar con lo nuevo: descarta eventos ya vencidos
    (fecha_evento anterior a hoy) y pasa 'pendiente' -> 'activo' cuando
    el dia programado ya llego."""
    reconciliados = []
    for ev in eventos:
        fecha_ev = (ev.get("fecha_evento") or ev.get("fecha_reporte") or "")[:10]
        if fecha_ev and fecha_ev < hoy_str:
            continue  # vencido, se descarta
        if fecha_ev == hoy_str and ev.get("estado") == "pendiente":
            ev["estado"] = "activo"
        reconciliados.append(ev)
    return reconciliados


def gas_post(payload, timeout=55, intentos=3):
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.post(GAS_URL, data=json.dumps(payload), timeout=timeout,
                               headers={"Content-Type": "text/plain"})
            if not r.text.strip():
                raise ValueError("Respuesta vacía de Apps Script")
            return r.json()
        except Exception as e:
            ultimo_error = e
            print(f"  ! Intento {intento}/{intentos} fallo para {payload.get('action')}: {e}")
            if intento < intentos:
                time.sleep(5 * intento)  # backoff: 5s, 10s...
    return {"ok": False, "error": str(ultimo_error)}


def main():
    eventos_activos = []

    for op in OPERADORES:
        print(f"\n=== {op['nombre']} ===")
        noticias = []
        links_vistos = set()
        for q in op["queries"]:
            for n in buscar_noticias(q):
                if n["link"] not in links_vistos:
                    links_vistos.add(n["link"])
                    noticias.append(n)
            time.sleep(0.5)
        print(f"  {len(noticias)} noticia(s) única(s) encontradas (de {len(op['queries'])} variantes de búsqueda)")

        # Agrupar por ciudad detectada -> fusionar el mejor dato de cada grupo
        # (una noticia puede decir el barrio, otra el circuito/subestacion del
        # mismo hecho; no queremos quedarnos solo con la primera que aparezca)
        grupos = {}  # ciudad -> {info fusionada, detalle, fuente, fecha}
        for n in noticias:
            texto = extraer_texto_articulo(n["link"])
            if not texto:
                continue
            info = parsear_reporte(texto, n["title"])

            ciudad = op["departamento"].split("/")[0].strip()
            for c in CIUDADES_COORD:
                if c in normalizar(n["title"]).lower() or c in normalizar(texto[:500]).lower():
                    ciudad = c.title()
                    break

            g = grupos.setdefault(ciudad, {
                "subestacion": "N/D", "circuito": "N/D", "inicio": "—", "fin": "—",
                "barrios": [], "detalle": n["title"][:180], "texto_completo": "",
                "fecha_reporte": n["published"].strftime("%Y-%m-%d %H:%M"), "fuente": n["link"],
            })
            g["texto_completo"] += " " + texto[:2000]
            if g["subestacion"] == "N/D" and info["subestacion"] != "N/D":
                g["subestacion"] = info["subestacion"]
                g["fuente"] = n["link"]  # la fuente mas informativa manda
            if g["circuito"] == "N/D" and info["circuito"] != "N/D":
                g["circuito"] = info["circuito"]
            if g["inicio"] == "—" and info["inicio"] != "—":
                g["inicio"], g["fin"] = info["inicio"], info["fin"]
            for b in info["barrios"]:
                if b not in g["barrios"]:
                    g["barrios"].append(b)

        for ciudad, g in grupos.items():
            lat, lng = geocodificar_ciudad(ciudad, op["lat"], op["lng"])
            estado = detectar_estado(g["texto_completo"], g["fin"])
            hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            evento = {
                "operador": op["nombre"], "ciudad": ciudad, "lat": lat, "lng": lng,
                "subestacion": g["subestacion"], "circuito": g["circuito"],
                "inicio": g["inicio"], "fin": g["fin"],
                "barrios": g["barrios"] if g["barrios"] else [ciudad],
                "detalle": g["detalle"],
                "fecha_reporte": g["fecha_reporte"],
                "fecha_evento": hoy_str,
                "fuente": g["fuente"],
                "estado": estado,
            }
            eventos_activos.append(evento)
            print(f"  + {ciudad} | circuito={g['circuito']} | subestacion={g['subestacion']}")

            # Si se detectó circuito o subestación explícito, alimenta la biblioteca histórica
            if g["circuito"] != "N/D" or g["subestacion"] != "N/D":
                gas_post({
                    "action": "actualizarBiblioteca",
                    "operador": op["nombre"], "departamento": op["departamento"],
                    "subestacion": g["subestacion"], "circuito": g["circuito"],
                    "barrios_nuevos": evento["barrios"],
                    "fecha": g["fecha_reporte"][:10],
                    "fuente": g["fuente"],
                })

        time.sleep(1)  # ser amable con los servidores de noticias

    print(f"\nTotal eventos nuevos detectados en esta corrida: {len(eventos_activos)}")

    hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    actuales_resp = gas_get({"action": "getCortes"})
    actuales = actuales_resp.get("eventos", []) if actuales_resp.get("ok") else []
    print(f"Eventos ya activos en el mapa (antes de reconciliar): {len(actuales)}")

    actuales_reconciliados = reconciliar_por_fecha(actuales, hoy_str)
    print(f"Eventos tras reconciliar por fecha (vencidos descartados, pendiente->activo si tocaba): {len(actuales_reconciliados)}")

    fusion = {clave_evento(ev): ev for ev in actuales_reconciliados}
    for ev in eventos_activos:
        fusion[clave_evento(ev)] = ev  # lo nuevo de esta corrida reemplaza lo viejo de esa misma ciudad+operador

    lista_final = list(fusion.values())
    print(f"Total final tras fusion: {len(lista_final)}")

    if len(lista_final) == 0:
        print("Lista final vacia: no se sobreescribe el mapa por seguridad.")
        return

    resultado = gas_post({"action": "saveCortes", "data": lista_final})
    print("Resultado saveCortes:", json.dumps(resultado))
    if not resultado.get("ok"):
        raise SystemExit(f"saveCortes fallo: {resultado}")


if __name__ == "__main__":
    main()
