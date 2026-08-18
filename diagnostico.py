"""
Diagnostico: consulta getCortes tal cual y guarda la respuesta cruda
(sin procesar) en un archivo del repo, para poder inspeccionarla desde
fuera sin depender de los logs de Actions.
"""
import os
import json
import requests
from datetime import datetime, timezone

GAS_URL = os.environ.get("GAS_URL", "").strip()
if not GAS_URL:
    raise SystemExit("Falta GAS_URL")

r = requests.get(GAS_URL, params={"action": "getCortes"}, timeout=55)
print("Status HTTP:", r.status_code)
print("Primeros 500 caracteres crudos:")
print(r.text[:500])

with open("diagnostico_cortes.json", "w", encoding="utf-8") as f:
    f.write(f"# Consultado: {datetime.now(timezone.utc).isoformat()}\n")
    f.write(r.text)

print("\nGuardado en diagnostico_cortes.json")
