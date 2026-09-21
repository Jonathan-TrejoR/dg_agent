# from google.adk.agents.llm_agent import Agent

# root_agent = Agent(
#     model='gemini-2.5-flash',
#     name='root_agent',
#     description='A helpful assistant for user questions.',
#     instruction='Answer user questions to the best of your knowledge',
# )


# from google.adk.agents.llm_agent import Agent

# # Mock tool implementation
# def get_current_time(city: str) -> dict:
#     """Returns the current time in a specified city."""
#     return {"status": "success", "city": city, "time": "10:30 AM"}

# root_agent = Agent(
#     model='gemini-2.5-flash',
#     name='root_agent',
#     description="Tells the current time in a specified city.",
#     instruction="You are a helpful assistant that tells the current time in cities. Use the 'get_current_time' tool for this purpose.",
#     tools=[get_current_time],
# )

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from pathlib import Path
from pypdf import PdfReader
from google.adk.agents import Agent
import os
from pathlib import Path

# Obtiene la ruta de la carpeta donde está este script agent.py
BASE_DIR = Path(__file__).resolve().parent
# Construye la ruta al PDF relativa a esta carpeta
PDF_PATH = BASE_DIR / "GD_Estándar de Nomenclatura_MESH.pdf"

# Ruta local al estándar en PDF
# PDF_PATH = r"C:\Users\JOTREJOR\Documents\Repositorios\agentic_ai\agent_dg2\GD_Estándar de Nomenclatura_MESH.pdf"

def validate_table_against_mesh_standard(table_name: str) -> dict:
    """Lee el estándar de nomenclatura MESH desde un PDF local y evalúa si el nombre de una tabla cumple las reglas.

    Args:
        table_name (str): El nombre de la tabla de BigQuery o Spark (ejemplo: 'stg_ventas_pos' o 'tb_clientes').

    Returns:
        dict: Estado de la lectura del archivo, contenido extraído del estándar y nombre de la tabla.
    """
    pdf_file = Path(PDF_PATH)
    
    if not pdf_file.exists():
        return {
            "status": "error",
            "error_message": f"No se encontró el archivo PDF en la ruta: {PDF_PATH}"
        }

    try:
        # Extraer el texto completo del PDF
        reader = PdfReader(pdf_file)
        pdf_text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                pdf_text += extracted + "\n"

        return {
            "status": "success",
            "table_to_validate": table_name,
            "mesh_standard_rules": pdf_text #[:4000]  # Se envía el estándar extraído al agente
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"Error al leer el archivo PDF: {str(e)}"
        }
# def get_weather(city: str) -> dict:
#     """Retrieves the current weather report for a specified city.

#     Args:
#         city (str): The name of the city for which to retrieve the weather report.

#     Returns:
#         dict: status and result or error msg.
#     """
#     if city.lower() == "new york":
#         return {
#             "status": "success",
#             "report": (
#                 "The weather in New York is sunny with a temperature of 25 degrees"
#                 " Celsius (77 degrees Fahrenheit)."
#             ),
#         }
#     else:
#         return {
#             "status": "error",
#             "error_message": f"Weather information for '{city}' is not available.",
#         }


# def get_current_time(city: str) -> dict:
#     """Returns the current time in a specified city.

#     Args:
#         city (str): The name of the city for which to retrieve the current time.

#     Returns:
#         dict: status and result or error msg.
#     """

#     if city.lower() == "new york":
#         tz_identifier = "America/New_York"
#     else:
#         return {
#             "status": "error",
#             "error_message": (
#                 f"Sorry, I don't have timezone information for {city}."
#             ),
#         }

#     tz = ZoneInfo(tz_identifier)
#     now = datetime.datetime.now(tz)
#     report = (
#         f'The current time in {city} is {now.strftime("%Y-%m-%d %H:%M:%S %Z%z")}'
#     )
#     return {"status": "success", "report": report}


# root_agent = Agent(
#     name="agent_dg",
#     model="gemini-2.5-flash",
#     description=(
#         "Eres el Agente Experto en Gobierno de Datos (FinOps y DataOps) de la empresa. \
#         Tu objetivo es auditar consultas y Stored Procedures de BigQuery"
#     ),
#     instruction=(
#         "You are a helpful agent who can answer user questions about the time and weather in a city."
#     ),
#     tools=[get_weather, get_current_time, validate_table_nomenclatures],
# )

# root_agent = Agent(
#     name="agent_dg",
#     model="gemini-2.5-flash",
#     description="Agente Experto en Gobierno de Datos para auditar consultas de BigQuery.",
#     instruction=(
#         "Eres un auditor de DataOps. Revisa las consultas SQL que proporcione el usuario "
#         "o las que leas desde Google Drive. Utiliza 'validate_table_nomenclatures' para verificar "
#         "los nombres de las tablas y reporta cualquier violación encontrada."
#     ),
#     tools=[get_weather, get_current_time, validate_table_nomenclatures],
# )



root_agent = Agent(
    name="agent_dg",
    model="gemini-2.5-pro",
    description="Agente Experto en Gobierno de Datos y MESH Naming Standards.",
    instruction=(
        "Eres un auditor de DataOps. Cuando el usuario te proporcione el nombre de una tabla, "
        "ejecuta la herramienta 'validate_table_against_mesh_standard'. "
        "Analiza las reglas contenidas en 'mesh_standard_rules' y responde si la tabla cumple "
        "o no la nomenclatura MESH, especificando qué regla se violó o se respetó."
    ),
    tools=[validate_table_against_mesh_standard]
)