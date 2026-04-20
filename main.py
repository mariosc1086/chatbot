from fastapi import FastAPI
from pydantic import BaseModel
import json
import pandas as pd

ruta = "/content/drive/MyDrive/INEI/ipc.xlsx"

df = pd.read_excel(ruta)

df.head()

def interpretar_pregunta(pregunta):

    prompt = f"""
Extrae los siguientes campos de la pregunta y responde SOLO en JSON válido.

  Campos:

- indicador:
  Puede ser uno o varios de estos valores exactos:
  - IPC_Lima
  - IPC_Nacional
  - Indice_Precio_Por_Mayor_Nacional
  - Indice_Precio_Maquinaria_Equipo
  - Indice_Precio_Materiales_Construccion

- anio:
  - Si hay un solo año → número
  - Si hay varios años → lista de números

- mes:
  - Si hay un solo mes → string en MAYÚSCULAS
  - Si hay varios meses → lista de strings en MAYÚSCULAS

- tipo:
  Puede ser uno o varios de estos valores:
  - INDICE_GENERAL
  - MENSUAL
  - ACUMULADA
  - ANUAL

- operacion:
  Uno de estos valores:
  - puntual
  - comparacion

---

REGLAS PARA "indicador":

- "Lima Metropolitana" o "IPC de Lima" → IPC_Lima
- "nivel nacional", "IPC nacional" → IPC_Nacional
- "Índice de Precios al Por Mayor" → Indice_Precio_Por_Mayor_Nacional
- "Maquinaria y Equipo" → Indice_Precio_Maquinaria_Equipo
- "Materiales de Construcción" → Indice_Precio_Materiales_Construccion

---

REGLAS PARA "anio":

- Si aparece "2024 y 2025" → [2024, 2025]
- Si aparece "entre 2020 y 2023" → [2020, 2021, 2022, 2023]
- Si hay más de un año → SIEMPRE lista

---

REGLAS PARA "mes":

- Convertir siempre a MAYÚSCULAS
- Si hay más de un mes → lista

---

REGLAS PARA "tipo":

- Si preguntan "¿cuánto aumentó?", "variación mensual" → MENSUAL
- Si dicen "acumulado" → ACUMULADA
- Si dicen "anual" → ANUAL
- Si solo piden el índice → INDICE_GENERAL

---

REGLAS PARA "operacion":

- Si preguntan por un valor específico → puntual
- Si comparan (ej: "2024 y 2025", "vs", "comparar") → comparacion

---

REGLAS GENERALES:

- NO inventes valores
- NO expliques
- NO uses markdown
- SOLO devuelve JSON válido
- Si la pregunta pide más de una cosa (ej: "ipc y variación") → devolver lista
- Ejemplo: ["INDICE_GENERAL", "MENSUAL"]
- Si la pregunta contiene "y" (ej: "ipc y variación") → devolver múltiples tipos

---

Pregunta: {pregunta}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Eres un asistente que extrae parámetros de consultas económicas y responde únicamente en JSON válido."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)

def normalizar_mes(mes):
    if mes == "SEPTIEMBRE":
        return "SETIEMBRE"
    return mes

def consultar_ipc_general(df, datos):

    df_filtrado = df.copy()

    # 🔹 indicador
    if "indicador" in datos:
        valores = datos["indicador"]
        if not isinstance(valores, list):
            valores = [valores]
        df_filtrado = df_filtrado[df_filtrado["INDICADOR"].isin(valores)]

    # 🔹 año
    if "anio" in datos:
        valores = datos["anio"]
        if not isinstance(valores, list):
            valores = [valores]
        df_filtrado = df_filtrado[df_filtrado["ANIO"].isin(valores)]

    # 🔹 mes
    if "mes" in datos:
        valores = datos["mes"]
        if not isinstance(valores, list):
            valores = [valores]

        valores = [normalizar_mes(v) for v in valores]

        df_filtrado = df_filtrado[df_filtrado["MES"].isin(valores)]

    # 🔹 tipo
    if "tipo" in datos:
        valores = datos["tipo"]
        if not isinstance(valores, list):
            valores = [valores]
        df_filtrado = df_filtrado[df_filtrado["TIPO"].isin(valores)]

    return df_filtrado

def generar_respuesta_gpt(pregunta, df_res, memoria):

    if df_res.empty:
        return "No se encontró información para la consulta."

    datos = df_res.to_dict(orient="records")

    contexto = f"""
Contexto previo:
Indicador: {memoria.get("indicador")}
Año: {memoria.get("anio")}
Mes: {memoria.get("mes")}
Tipo: {memoria.get("tipo")}
"""

    prompt = f"""
Eres un analista económico.

{contexto}

Con base en estos datos:
{datos}

Responde de forma:
- MUY breve
- directa
- No repetir información
- No separar en párrafos
- sin explicaciones adicionales
- sin suposiciones
- sin pedir datos adicionales

Si hay múltiples resultados, respóndelos en una sola frase clara.

Pregunta: {pregunta}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    return response.choices[0].message.content

app = FastAPI()

class Pregunta(BaseModel):
    texto: str

# 🔥 memoria simple (por sesión básica)
memoria = {}

@app.post("/chat")
def chat(p: Pregunta):

    global memoria

    try:
        datos = interpretar_pregunta(p.texto)

        datos_limpios = {
            k: v for k, v in datos.items()
            if v not in [None, "", []]
        }

        datos_completos = memoria.copy()
        datos_completos.update(datos_limpios)

        memoria.update(datos_limpios)

        df_res = consultar_ipc_general(df, datos_completos)

        respuesta = generar_respuesta_gpt(p.texto, df_res, memoria)

        return {"respuesta": respuesta}

    except Exception as e:
        return {"respuesta": str(e)}