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
  - minimo
  - maximo
  - promedio

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
- Si preguntan por el valor maximo o máximo → maximo
- Si preguntan por el valor minimo o mínimo → minimo
- "máximo", "maximo", "mayor" → maximo
- "mínimo", "minimo", "menor" → minimo
- "promedio", "media" → promedio

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

# Aplicaciones de operaciones basicas de estadistica
def calcular_maximo(df):
    fila = df.loc[df["VALOR"].astype(float).idxmax()]
    return {
        "valor": round(fila["VALOR"], 2),
        "mes": fila["MES"],
        "anio": fila["ANIO"]
    }

def calcular_minimo(df):
    fila = df.loc[df["VALOR"].astype(float).idxmin()]
    return {
        "valor": round(fila["VALOR"], 2),
        "mes": fila["MES"],
        "anio": fila["ANIO"]
    }

def calcular_promedio(df):
    valor = df["VALOR"].astype(float).mean()
    return {
        "valor": round(valor, 2)
    }

def generar_respuesta_gpt(pregunta, df_res, memoria, resultado=None):

    if df_res.empty:
        return "No se encontró información para la consulta."
    
    operacion = memoria.get("operacion")

    tipo = memoria.get("tipo")

    # 🔥 manejar tipo lista
    if isinstance(tipo, list):
        tipo_base = tipo[0]
    else:
        tipo_base = tipo

    # 🔥 unidad
    if tipo_base == "INDICE_GENERAL":
        unidad = "puntos"
    else:
        unidad = "%"

    # 🔥 usar funciones existentes
    if operacion == "maximo":
        res = calcular_maximo(df_res)
        resultado = f"valor={res['valor']}, mes={res['mes']}, anio={res['anio']}, unidad={unidad}"

    elif operacion == "minimo":
        res = calcular_minimo(df_res)
        resultado = f"valor={res['valor']}, mes={res['mes']}, anio={res['anio']}, unidad={unidad}"

    elif operacion == "promedio":
        res = calcular_promedio(df_res)
        resultado = f"valor={res['valor']}, unidad={unidad}"

    else:
        resultado = None

    if resultado:
        datos = resultado
    else:
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

Resultado calculado:
{resultado if resultado else datos}

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

        # 🔥 AQUÍ VA 👇 (ANTES DEL FILTRO)
        # solo elimina mes si el usuario NO lo mencionó
        if datos_completos.get("operacion") in ["maximo", "minimo", "promedio"] and "mes" not in datos_limpios:
            datos_completos.pop("mes", None)

        # 🔥 ahora sí consulta
        df_res = consultar_ipc_general(df, datos_completos)

        if df_res.empty:
            return {
                "respuesta": "No encontré datos para esa consulta. Intenta con otro mes, año o tipo de IPC."
            }

        # 🔥 NUEVO BLOQUE
        operacion = datos_completos.get("operacion", "puntual")

        tipo = datos_completos.get("tipo")

        # 🔥 manejar lista
        if isinstance(tipo, list):
            tipo_base = tipo[0]
        else:
            tipo_base = tipo

        # 🔥 unidad
        if tipo_base == "INDICE_GENERAL":
            unidad = "puntos"
        else:
            unidad = "%"

        resultado = None

        if operacion == "maximo":
            resultado = calcular_maximo(df_res)

        elif operacion == "minimo":
            resultado = calcular_minimo(df_res)

        elif operacion == "promedio":
            resultado = calcular_promedio(df_res)

        # 🔥 si no es agregación → GPT
        respuesta = generar_respuesta_gpt(p.texto, df_res, memoria, resultado)

        return {"respuesta": respuesta}

    except Exception as e:
        return {"respuesta": str(e)}