from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import json
import pandas as pd
from fastapi.middleware.cors import CORSMiddleware

ruta = "ipc.xlsx"

df = pd.read_excel(ruta)

df.head()

import os
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

- Si preguntan "¿cuánto aumentó?", "variación mensual", "variacion mensual", "variación", "variacion" → MENSUAL
- Si dicen "acumulado", "variación acumulada", "variacion acumulada" → ACUMULADA
- Si dicen "anual", "variación anual", "variacion anual" → ANUAL
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

Los datos tienen esta estructura:

- INDICE_GENERAL: nivel del índice (no es porcentaje)
- MENSUAL: variación mensual en porcentaje
- ACUMULADA: variación acumulada en porcentaje
- ANUAL: variación anual en porcentaje

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
- NO confundas el índice con variación
- El índice se expresa en puntos
- La variación se expresa en porcentaje

Si hay múltiples resultados, respóndelos en una sola frase clara.

Pregunta: {pregunta}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    return response.choices[0].message.content

def clasificar_intencion(pregunta):

    prompt = f"""
Clasifica la intención de la siguiente pregunta.

Opciones:
- saludo
- consulta_ipc

Reglas:
- Saludos, cortesía, conversación → saludo
- Preguntas sobre IPC, inflación, índices → consulta_ipc

Pregunta: {pregunta}

Responde SOLO una palabra.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return response.choices[0].message.content.strip().lower()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔥 permite acceso desde cualquier web
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Pregunta(BaseModel):
    texto: str

@app.get("/")
def home():
    return {"mensaje": "API del Chatbot IPC funcionando"}

# 🔥 memoria simple (por sesión básica)
memoria = {}

@app.post("/chat")
def chat(p: Pregunta):

    global memoria

    mensaje = p.texto.lower().strip()

    saludos = ["hola", "buenos dias", "buenas tardes", "buenas noches"]
    agradecimientos = ["gracias", "ok", "listo"]

    if len(mensaje) < 3:
        return {"respuesta": "¿Puedes darme más detalles? 😊"}

    if mensaje in saludos:
        return {"respuesta": "👋 Hola, soy tu asistente de inflación. ¿Qué deseas consultar?"}

    if any(mensaje.startswith(a) for a in agradecimientos):
        return {"respuesta": "😊 ¡Con gusto! Si necesitas algo más, dime."}

    try:
        intencion = clasificar_intencion(p.texto)

        if intencion == "saludo":
            return {
                "respuesta": "👋 Hola, soy tu asistente de inflación. ¿Qué deseas consultar?"
            }

        datos = interpretar_pregunta(p.texto)

        datos_limpios = {
            k: v for k, v in datos.items()
            if v not in [None, "", []]
        }

        datos_completos = memoria.copy()
        datos_completos.update(datos_limpios)

        # 🔥 memoria segura
        for k, v in datos_limpios.items():
            if v:
                memoria[k] = v

        df_res = consultar_ipc_general(df, datos_completos)

        if df_res.empty:
            return {
                "respuesta": "No encontré datos 😕. Prueba con: 'IPC Lima enero 2024'."
            }

        respuesta = generar_respuesta_gpt(p.texto, df_res, memoria)

        return {"respuesta": respuesta}

    except Exception as e:
        return {"respuesta": str(e)}