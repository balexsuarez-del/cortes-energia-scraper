"""
Carga masiva del catalogo de subestaciones/circuitos de Afinia
(Bolivar, Cordoba, Sucre, Cesar) a la Biblioteca. Fuente: catalogo
proporcionado por el usuario (referencia interna de Afinia).

Nota: los sectores listados son a nivel de SUBESTACION completa, no
desglosados por circuito individual (esa granularidad no esta
disponible en la fuente). Se registra igual cada circuito individual
en la Biblioteca para que futuras menciones en prensa/scraper puedan
matchear por nombre exacto de circuito, con la lista de sectores de su
subestacion como aproximacion hasta que aparezca un reporte mas
especifico.
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
FUENTE = "Catalogo interno Afinia (proporcionado por el usuario, 2026-08-19)"

# (departamento, subestacion, [circuitos], [sectores])
CATALOGO = [
    ("Bolivar", "Subestacion Chambacu",
     ["Chambacu 1","Chambacu 2","Chambacu 3","Chambacu 4","Chambacu 5","Chambacu 6"],
     ["Centro Historico","San Diego","Getsemani","El Cabrero","Crespo","Marbella","Marbella Norte"]),
    ("Bolivar", "Subestacion Zaragocilla",
     ["Zaragocilla 1","Zaragocilla 2","Zaragocilla 3","Zaragocilla 4","Zaragocilla 5","Zaragocilla 6","Zaragocilla 7"],
     ["Zaragocilla","El Bosque","Espana","Piedra de Bolivar","Los Calamares","Escallon Villa","Consulado","Amberes"]),
    ("Bolivar", "Subestacion Ternera",
     ["Ternera 1","Ternera 2","Ternera 3","Ternera 4","Ternera 5","Ternera 6","Ternera 7"],
     ["Ternera","San Fernando","Villa Sol","La Concepcion","El Recreo","Alameda","San Jose de los Campanos"]),
    ("Bolivar", "Subestacion Bosque y Termocartagena",
     ["Bosque 1","Bosque 2","Bosque 3","Bosque 4","Bosque 5","Bosque 6","Bosque 7","Bosque 8","Mamonal"],
     ["Zona Industrial de Mamonal","Ceballos","Santa Clara","Albornoz","Manga"]),
    ("Bolivar", "Subestacion El Carmen de Bolivar",
     ["El Carmen 1","El Carmen 2","El Carmen 3"],
     ["Zona urbana El Carmen de Bolivar","San Jacinto","San Juan Nepomuceno","Montes de Maria"]),

    ("Cordoba", "Subestacion Monteria (Nueva Monteria)",
     ["Monteria 1","Monteria 2","Monteria 3","Monteria 4","Monteria 5","Monteria 6"],
     ["Centro de Monteria","La Granja","Chuchurubi","Sectores ribereños"]),
    ("Cordoba", "Subestacion Mocari",
     ["Mocari 1","Mocari 2","Mocari 3"],
     ["Comuna 8","Mocari","Urbanizaciones del norte de Monteria","Via a Cerete"]),
    ("Cordoba", "Subestacion Chinu y Sahagun",
     ["Chinu 1","Chinu 2","Sahagun 1","Sahagun 2","Sahagun 3"],
     ["Chinu","Sahagun","Conexiones hacia el San Jorge"]),
    ("Cordoba", "Subestacion Cerromatoso / Montelibano",
     ["Montelibano 1","Montelibano 2","Puerto Libertad"],
     ["Montelibano","La Apartada","Puerto Libertador"]),

    ("Sucre", "Subestacion Sincelejo (Sierra Maestra / Boston)",
     ["Sincelejo 1","Sincelejo 2","Sincelejo 3","Sincelejo 4","Sincelejo 5","Sincelejo 6"],
     ["Zona centrica de Sincelejo","Camilo Torres","La Selva","Boston","La Ford","Majagual"]),
    ("Sucre", "Subestacion Corozal",
     ["Corozal 1","Corozal 2"],
     ["Zona urbana y rural de Corozal","Morroa","Los Palmitos"]),
    ("Sucre", "Subestacion San Marcos",
     ["San Marcos 1","San Marcos 2"],
     ["Region de la Mojana sucreña","San Marcos","San Benito Abad"]),

    ("Cesar", "Subestacion Salguero y Valledupar",
     ["Salguero 1","Salguero 2","Salguero 3","Salguero 4","Salguero 5","Guatapuri"],
     ["Centro y sur de Valledupar","Fundacion","Los Fundadores","La Nevada","Villa Castro"]),
    ("Cesar", "Subestacion La Loma (El Paso)",
     ["La Loma 1","La Loma 2"],
     ["Corredor minero del Cesar","La Loma","El Paso","Chiriguana"]),
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
                "operador": "Afinia",
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
