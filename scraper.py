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


def gas_post(payload, timeout=55):
    try:
        r = requests.post(GAS_URL, data=json.dumps(payload), timeout=timeout,
                           headers={"Content-Type": "text/plain"})
        return r.json()
    except Exception as e:
        print(f"  ! Error llamando a GAS ({payload.get('action')}): {e}")
        return {"ok": False, "error": str(e)}


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
            lat, lng = geocodificar_ciudad(ciudad, op["lat"], op["lng"])

            evento = {
                "operador": op["nombre"], "ciudad": ciudad, "lat": lat, "lng": lng,
                "subestacion": info["subestacion"], "circuito": info["circuito"],
                "inicio": info["inicio"], "fin": info["fin"],
                "barrios": info["barrios"] if info["barrios"] else [ciudad],
                "detalle": n["title"][:180],
                "fecha_reporte": n["published"].strftime("%Y-%m-%d %H:%M"),
                "fuente": n["link"],
            }
            eventos_activos.append(evento)
            print(f"  + {ciudad} | circuito={info['circuito']} | subestacion={info['subestacion']}")

            # Si se detectó circuito o subestación explícito, alimenta la biblioteca histórica
            if info["circuito"] != "N/D" or info["subestacion"] != "N/D":
                gas_post({
                    "action": "actualizarBiblioteca",
                    "operador": op["nombre"], "departamento": op["departamento"],
                    "subestacion": info["subestacion"], "circuito": info["circuito"],
                    "barrios_nuevos": evento["barrios"],
                    "fecha": n["published"].strftime("%Y-%m-%d"),
                    "fuente": n["link"],
                })

            time.sleep(1)  # ser amable con los servidores de noticias

    print(f"\nTotal eventos activos detectados: {len(eventos_activos)}")
    if len(eventos_activos) == 0:
        print("Sin eventos nuevos en esta corrida: no se sobreescribe el mapa (se deja el estado anterior).")
        return
    resultado = gas_post({"action": "saveCortes", "data": eventos_activos})
    print("Resultado saveCortes:", json.dumps(resultado))
    if not resultado.get("ok"):
        raise SystemExit(f"saveCortes fallo: {resultado}")


if __name__ == "__main__":
    main()
