"""
Aplica eventos de cortes encontrados manualmente (busqueda de alta
precision, ej. por el skill cortes-energia-colombia), fusionandolos con
lo que ya esta activo en el mapa en vez de sobreescribirlo todo.

Uso: EVENTOS='[...]' python3 aplicar_manual.py
"""

import os
import json
import time
import requests

GAS_URL = os.environ.get("GAS_URL", "").strip()
EVENTOS_JSON = os.environ.get("EVENTOS", "[]")

if not GAS_URL:
    raise SystemExit("Falta GAS_URL")


def gas_post(payload, timeout=55, intentos=3):
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.post(GAS_URL, data=json.dumps(payload), timeout=timeout,
                               headers={"Content-Type": "text/plain"})
            if not r.text.strip():
                raise ValueError("Respuesta vacia de Apps Script")
            return r.json()
        except Exception as e:
            ultimo_error = e
            print(f"  ! Intento {intento}/{intentos} fallo: {e}")
            if intento < intentos:
                time.sleep(5 * intento)
    return {"ok": False, "error": str(ultimo_error)}


def gas_get(params, timeout=55, intentos=3):
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.get(GAS_URL, params=params, timeout=timeout)
            if not r.text.strip():
                raise ValueError("Respuesta vacia de Apps Script")
            return r.json()
        except Exception as e:
            ultimo_error = e
            print(f"  ! Intento {intento}/{intentos} fallo: {e}")
            if intento < intentos:
                time.sleep(5 * intento)
    return {"ok": False, "error": str(ultimo_error)}


def clave(ev):
    return (ev.get("operador", "").strip().lower(), ev.get("ciudad", "").strip().lower())


def main():
    nuevos = json.loads(EVENTOS_JSON)
    print(f"Eventos nuevos recibidos: {len(nuevos)}")

    actuales_resp = gas_get({"action": "getCortes"})
    actuales = actuales_resp.get("eventos", []) if actuales_resp.get("ok") else []
    print(f"Eventos activos actuales en el mapa: {len(actuales)}")

    fusion = {clave(ev): ev for ev in actuales}
    for ev in nuevos:
        fusion[clave(ev)] = ev  # el nuevo reemplaza al viejo de esa misma ciudad+operador

    lista_final = list(fusion.values())
    print(f"Total tras fusion: {lista_final and len(lista_final)}")

    resultado = gas_post({"action": "saveCortes", "data": lista_final})
    print("Resultado saveCortes:", json.dumps(resultado))
    if not resultado.get("ok"):
        raise SystemExit(f"saveCortes fallo: {resultado}")

    for ev in nuevos:
        if ev.get("circuito", "N/D") != "N/D" or ev.get("subestacion", "N/D") != "N/D":
            r = gas_post({
                "action": "actualizarBiblioteca",
                "operador": ev.get("operador", ""),
                "departamento": ev.get("ciudad", ""),
                "subestacion": ev.get("subestacion", "N/D"),
                "circuito": ev.get("circuito", "N/D"),
                "barrios_nuevos": ev.get("barrios", []),
                "fecha": ev.get("fecha_reporte", "")[:10],
                "fuente": ev.get("fuente", ""),
            })
            print(f"  Biblioteca [{ev.get('circuito')}/{ev.get('subestacion')}]:", r.get("resultado", r))


if __name__ == "__main__":
    main()
