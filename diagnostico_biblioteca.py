import os
import json
import requests

GAS_URL = os.environ.get("GAS_URL", "").strip()
r = requests.get(GAS_URL, params={"action": "getBiblioteca"}, timeout=55)
data = r.json()
registros = data.get("data", [])
print(f"Total registros en Biblioteca: {len(registros)}")
with open("diagnostico_biblioteca.json", "w", encoding="utf-8") as f:
    json.dump(registros, f, ensure_ascii=False, indent=2)
print("Guardado en diagnostico_biblioteca.json")
