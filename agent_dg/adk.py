import asyncio
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
import os
from google.genai import types

os.environ["GOOGLE_CLOUD_PROJECT"] = "crp-pro-cx-orquestacion"  # Reemplaza por tu ID de GCP
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

# 1. Definimos el agente
# (En ADK el parámetro model suele recibir directamente la cadena del modelo)
mi_agente = Agent(
    name="agente_explorador",
    model="gemini-2.5-flash",
    instruction="Eres un ingeniero de datos experto. Responde de forma concisa y técnica."
)

# 2. Creación del Runner para orquestar la ejecución y la memoria
runner = InMemoryRunner(agent=mi_agente, app_name="mi_app")

async def main():
    print("Iniciando agente... (Escribe 'salir' para terminar)\n")

    # Creamos una sesión para mantener la conversación
    session = await runner.session_service.create_session(
        app_name="mi_app",
        user_id="usuario_local"
    )
    
    while True:
        # Leemos el input desde la terminal
        user_input = input("Tú: ")
        
        if user_input.lower() in ['salir', 'exit', 'quit']:
            break
            
        print("Agente pensando...")
        
        # Empaquetamos el mensaje en el formato que requiere ADK
        user_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_input)]
        )
        
        # Ejecutamos el agente a través del Runner usando run_async
        async for event in runner.run_async(
            user_id="usuario_local",
            session_id=session.id,
            new_message=user_message
        ):
            # Procesamos los eventos emitidos por el agente
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(f"\nAgente: {part.text}\n")
                        
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())