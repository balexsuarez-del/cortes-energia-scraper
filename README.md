# Scraper de Cortes de Energía — Colombia

Corre cada hora vía GitHub Actions, busca noticias recientes por operador en
Google News RSS, extrae circuito/subestación/barrios cuando el comunicado lo
menciona, y actualiza tu Google Sheet a través del Apps Script existente.

## Qué hace cada acción

- `saveCortes`: reemplaza la lista de "eventos activos" que ve el mapa del
  calendario (⚡ Cortes) — es el estado de "ahora mismo".
- `actualizarBiblioteca`: solo se llama cuando el texto de la noticia
  menciona un circuito o subestación explícitos. Agrega/actualiza el
  catálogo histórico deduplicado (hoja `Biblioteca`).

## Instalación (una sola vez)

1. Crea un repo nuevo en GitHub (ej: `cortes-energia-scraper`) o agrega estos
   archivos a uno existente, manteniendo esta misma estructura de carpetas:
   ```
   scraper.py
   requirements.txt
   .github/workflows/cortes-energia.yml
   ```

2. En el repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `GAS_URL` = la URL `/exec` de tu Apps Script (la misma que usa `calendario.html`)
   - `GOOGLE_MAPS_API_KEY` = (opcional) si quieres geocodificación real en vez
     del diccionario estático de ciudades. Sin esta key, el scraper igual
     funciona, solo que ubica a nivel de ciudad conocida o el centroide del
     departamento del operador.

3. Listo. El workflow corre solo cada hora (`cron: '0 * * * *'`). También
   puedes lanzarlo manualmente: pestaña **Actions** → "Actualizar cortes de
   energía" → **Run workflow**.

## Limitaciones honestas (para que no esperes más de lo que da)

- La extracción de circuito/subestación/barrios es por **expresiones
  regulares sobre texto de noticias**, no un modelo de lenguaje. Funciona
  bien cuando el operador redacta de forma consistente (Afinia y Air-e
  suelen decir "Circuito X", "Subestación Y"); para comunicados más libres
  (Enel, EPM) es probable que solo capture ciudad y barrios, dejando
  circuito/subestación como `N/D`. Esto es esperado, no un bug.
- Depende de que Google News haya indexado la noticia — si un operador
  publica solo en su propia web o X/Twitter sin que ningún medio lo
  replique, el scraper no lo verá. Se puede ampliar más adelante agregando
  scraping directo de esas páginas si hace falta.
- La geocodificación sin `GOOGLE_MAPS_API_KEY` es a nivel de ciudad
  conocida (diccionario fijo en `CIUDADES_COORD`), no de barrio exacto.

## Cómo ampliar la precisión con el tiempo

- Agrega ciudades nuevas a `CIUDADES_COORD` en `scraper.py` a medida que
  aparezcan en los reportes.
- Si un operador cambia su forma de redactar y las regex dejan de
  capturar bien, ajusta `RE_CIRCUITO` / `RE_SUBESTACION` / `RE_BARRIOS`.
- Con `GOOGLE_MAPS_API_KEY` activa, la precisión de ubicación mejora sin
  tocar código.
