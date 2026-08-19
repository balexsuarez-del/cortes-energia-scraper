"""
Carga masiva del catalogo de subestaciones/circuitos de Air-e
(Atlantico, Magdalena, La Guajira) a la Biblioteca. Fuente: catalogo
proporcionado por el usuario (referencia interna de Air-e).
"""
import os
import json
import time
import requests
from datetime import datetime, timezone

GAS_URL = os.environ.get("GAS_URL", "").strip()
if not GAS_URL:
    raise SystemExit("Falta GAS_URL")

FECHA_HOY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FUENTE = "Catalogo interno Air-e (proporcionado por el usuario, 2026-08-19)"

CATALOGO = [
    ("Atlantico", "Subestacion Silencio",
     ["Silencio 5","Silencio 6","Silencio 12","Silencio Campo Alegre","Silencio Olaya","Silencio Mercedes","Silencio San Felipe"],
     ["Campo Alegre","Las Delicias","Mercedes","Olaya","San Felipe","El Porvenir","Colombia"]),
    ("Atlantico", "Subestacion Riomar y Nueva Barranquilla",
     ["Riomar 11","Riomar 13","Riomar Las Flores","Riomar Nogales","Riomar Buenavista","Riomar Castellana"],
     ["Altos del Prado","Riomar","Villa Santos","Buenavista","La Castellana","Las Flores"]),
    ("Atlantico", "Subestacion La Union y El Rio",
     ["La Union 1","La Union 2","La Union 6","La Union Ferry","La Union Primero de Mayo","La Union Boyaca"],
     ["La Union","San Roque","Rebolo","Chiquinquira","Simon Bolivar","Las Nieves","Ferry"]),
    ("Atlantico", "Subestacion Caracoli y Cordialidad (Soledad/Galapa)",
     ["Caracoli 1","Caracoli 2","Caracoli 3","Caracoli 5","Cordialidad 8","Cordialidad 9","Galapa","Pital de Megua"],
     ["Soledad 2000","Los Robles","Villa Carmen","Galapa","Baranoa"]),

    ("Magdalena", "Subestacion Bonda y Rio Cordoba (Santa Marta/Cienaga)",
     ["Bonda 1","Bonda 2","Cienaga 1","Cienaga 2","Rio Cordoba"],
     ["Bonda","El Rodadero","Cienaga","Zona Bananera","Corregimientos de la Sierra Nevada"]),
    ("Magdalena", "Subestacion Gaira y Zawady",
     ["Gaira 1","Gaira 2","Zawady"],
     ["Gaira","El Rodadero Sur","Pozos Colorados","Sectores agricolas del Magdalena medio"]),

    ("La Guajira", "Subestacion Riohacha y Cuestecitas",
     ["Riohacha 1","Riohacha 2","Riohacha 3","Cuestecitas 1","Cuestecitas 2"],
     ["Zona urbana de Riohacha","Hatonuevo","Barrancas"]),
    ("La Guajira", "Subestacion Maicao, Fonseca y San Juan",
     ["Maicao 1","Maicao 2","Maicao 3","Maicao 4","Fonseca","San Juan del Cesar"],
     ["Cabecera de Maicao","San Juan del Cesar","Fonseca","Zonas fronterizas"]),
]


def gas_post(payload, timeout=55, intentos=3):
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = requests.post(GAS_URL, data=json.dumps(payload), timeout=timeout,
                               headers={"Content-Type": "text/plain"})
            if not r.text.strip():
                raise ValueError("Respuesta vacia")
            return r.json()
        except Exception as e:
            ultimo_error = e
            print(f"    ! intento {intento}/{intentos} fallo: {e}")
            if intento < intentos:
                time.sleep(4 * intento)
    return {"ok": False, "error": str(ultimo_error)}


def main():
    total = 0
    nuevos = 0
    actualizados = 0
    for departamento, subestacion, circuitos, sectores in CATALOGO:
        for circuito in circuitos:
            total += 1
            r = gas_post({
                "action": "actualizarBiblioteca",
                "operador": "Air-e",
                "departamento": departamento,
                "subestacion": subestacion,
                "circuito": circuito,
                "barrios_nuevos": sectores,
                "fecha": FECHA_HOY,
                "fuente": FUENTE,
            })
            resultado = r.get("resultado", "error")
            if resultado == "nuevo":
                nuevos += 1
            elif resultado == "actualizado":
                actualizados += 1
            print(f"  [{total}] {subestacion} / {circuito} -> {resultado}")
            time.sleep(0.3)

    print(f"\nTotal procesados: {total} | Nuevos: {nuevos} | Actualizados: {actualizados}")


if __name__ == "__main__":
    main()
