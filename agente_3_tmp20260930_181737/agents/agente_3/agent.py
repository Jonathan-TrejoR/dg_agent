import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from google.adk.agents import Agent
except ImportError:
    try:
        from google.adk.agents.llm_agent import Agent
    except ImportError:
        class Agent:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)


# =====================================================================
# CONFIGURACIÓN DE RUTAS Y CACHÉ EN MEMORIA (0 ms)
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "GD_Estándar de Nomenclatura_MESH.pdf"
GUIDE_PATH = BASE_DIR / "guia_antipatrones_bigquery.md"

_CACHED_PDF_TEXT: Optional[str] = None
_CACHED_GUIDE_TEXT: Optional[str] = None


# =====================================================================
# BLOQUE 1: VALIDACIÓN DE NOMENCLATURA MESH (INTACTO)
# =====================================================================

def validate_table_against_mesh_standard(table_name: str) -> dict:
    """Lee el estándar de nomenclatura MESH desde el archivo PDF local y evalúa si el nombre de una tabla cumple las reglas."""
    global _CACHED_PDF_TEXT
    if _CACHED_PDF_TEXT is not None:
        return {
            "status": "success",
            "table_to_validate": table_name,
            "mesh_standard_rules": _CACHED_PDF_TEXT
        }

    pdf_file = Path(PDF_PATH)
    if not pdf_file.exists():
        return {
            "status": "error",
            "error_message": f"No se encontró el archivo PDF en la ruta: {PDF_PATH}"
        }

    try:
        if PdfReader is None:
            return {
                "status": "error",
                "error_message": "El paquete 'pypdf' no está disponible en el entorno."
            }
        reader = PdfReader(pdf_file)
        pdf_text = ""
        for page in reader.pages:
            extracted = page.extract() if hasattr(page, 'extract') else page.extract_text()
            if extracted:
                pdf_text += extracted + "\n"

        _CACHED_PDF_TEXT = pdf_text
        return {
            "status": "success",
            "table_to_validate": table_name,
            "mesh_standard_rules": _CACHED_PDF_TEXT
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"Error al leer el archivo PDF: {str(e)}"
        }


# =====================================================================
# BLOQUE 2: LECTURA Y CACHÉ DE LA GUÍA DE ANTIPATRONES (.MD)
# =====================================================================

def get_sql_optimization_rules_and_standards(topic: str = "all") -> dict:
    """Lee la guía unificada de antipatrones y directrices FinOps desde el archivo local .md con caché en memoria."""
    global _CACHED_GUIDE_TEXT
    if _CACHED_GUIDE_TEXT is not None:
        return {
            "status": "success",
            "topic": topic,
            "rules": _CACHED_GUIDE_TEXT
        }

    guide_file = Path(GUIDE_PATH)
    if guide_file.exists():
        try:
            _CACHED_GUIDE_TEXT = guide_file.read_text(encoding="utf-8")
            return {
                "status": "success",
                "topic": topic,
                "rules": _CACHED_GUIDE_TEXT
            }
        except Exception:
            pass

    _CACHED_GUIDE_TEXT = (
        "Pilar 1 (I/O): 1.1 selectStar, 1.12 partitionPruningDisabled, 1.18 unpartitionedMergeTarget.\n"
        "Pilar 2 (Slots/Shuffle): 1.5 joinOrder, 1.14 selfJoin, 1.13 skewedJoinKeys.\n"
        "Pilar 3 (Ventanas): 1.6 latestRecord, 1.16 redundantUnionAll.\n"
        "Pilar 4 (Aritmética/Cadenas): 1.15 prematureRegexp, 1.11 whereOrder, 1.26 timeFunctionMemoization.\n"
        "Pilar 5 (SPs): 1.27 iterativeRowByRow, 1.28 unhandledExceptionLogging, 1.2 missingDropStatement.\n"
        "Pilar 6 (UDFs): 1.29 javascriptUDFs."
    )
    return {
        "status": "success",
        "topic": topic,
        "rules": _CACHED_GUIDE_TEXT
    }


# =====================================================================
# BLOQUE 3: MOTOR DE AUDITORÍA Y EXTRACCIÓN DE METADATOS
# =====================================================================

_RE_COMMENTS_BLOCK = re.compile(r'/\*.*?\*/', re.DOTALL)
_RE_COMMENTS_LINE = re.compile(r'(--|#).*?$', re.MULTILINE)
_RE_STRINGS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", re.DOTALL)

# Pilar 1: I/O y Particiones
_RE_SELECT_STAR = re.compile(r'\bSELECT\s+(?:DISTINCT\s+)?(?:\*|[a-zA-Z0-9_]+\.\*)(?!\s*\w+\.)', re.IGNORECASE)
_RE_PART_FUNC = re.compile(r'(?:DATE|DATETIME|TIMESTAMP|DATE_TRUNC|TIMESTAMP_TRUNC|CAST|EXTRACT)\s*\(\s*[`\w\.]+\s*\)\s*(=|<|>|<=|>=|BETWEEN)', re.IGNORECASE)
_RE_MERGE_STMT = re.compile(r'\bMERGE\s+(?:INTO\s+)?([`\w\.\-]+)\s+.*?\bON\b\s+([^;\n]+)', re.IGNORECASE)
_RE_ORDER_IN_CTE = re.compile(r'WITH\s+.*ORDER\s+BY\s+[\w\.\,\s]+(?!\s+LIMIT\s+\d+)\s*\)', re.IGNORECASE | re.DOTALL)

# Pilar 2: Slots y Shuffle
_RE_IMPLICIT_JOIN = re.compile(r'FROM\s+[`\w\.\-]+(?:\s+(?:AS\s+)?[a-zA-Z0-9_]+)?\s*,\s*[`\w\.\-]+', re.IGNORECASE)
_RE_JOIN_CLAUSE = re.compile(r'JOIN\s+([`\w\.\-]+)\s+(?:AS\s+)?(\w+)?\s*ON\s+([^;\n]+)', re.IGNORECASE)
_RE_SKEWED_CHECK = re.compile(r'IS\s+NOT\s+NULL|!=\s*[\'"]99999[\'"]|!=\s*[\'"]-1[\'"]', re.IGNORECASE)
_RE_CAST_IN_JOIN = re.compile(r'JOIN\s+.*?ON\s+.*?\bCAST\s*\(', re.IGNORECASE)
_RE_COUNT_DISTINCT = re.compile(r'\bCOUNT\s*\(\s*DISTINCT\b', re.IGNORECASE)
_RE_DISTINCT_AND_GROUP = re.compile(r'\bSELECT\s+DISTINCT\b.*?\bGROUP\s+BY\b', re.IGNORECASE | re.DOTALL)

# Pilar 3: Analítica y Ventanas
_RE_ORDER_LIMIT1 = re.compile(r'ORDER\s+BY\s+[`\w\.\-]+\s+(?:ASC|DESC)\s+LIMIT\s+1\b', re.IGNORECASE)
_RE_OVER = re.compile(r'OVER\s*\(', re.IGNORECASE)
_RE_UNION_ALL = re.compile(r'\bUNION\s+ALL\b', re.IGNORECASE)

# Pilar 4: Cadenas y Aritmética
_RE_PREMATURE_REGEXP = re.compile(r'WHERE\s+REGEXP_(?:CONTAINS|EXTRACT|REPLACE)\s*\(.*?\)\s+AND\s+[`\w\.]+\s*=', re.IGNORECASE | re.DOTALL)
_RE_MULTI_UNNEST = re.compile(r'\(\s*SELECT\s+.*?FROM\s+UNNEST\(', re.IGNORECASE)
_RE_SUBQUERY_IN = re.compile(r'WHERE\s+[`\w\.]+\s+IN\s*\(\s*SELECT\s+[`\w\.]+\s+FROM', re.IGNORECASE)
_RE_UNSAFE_DIV = re.compile(r'[\w\)]\s*/\s*[`\w\.]+', re.IGNORECASE)
_RE_SAFE_DIV = re.compile(r'SAFE_DIVIDE|NULLIF', re.IGNORECASE)
_RE_REPEATED_TIME_FUNC = re.compile(r'FORMAT_DATETIME\s*\(.*?\b(?:CURRENT_DATETIME|CURRENT_DATE)\b.*?\)', re.IGNORECASE)

# Pilar 5: Procedimientos y Scripts
_RE_LOOPS = re.compile(r'\b(WHILE\b|LOOP\b|FOR\s+\w+\s+IN\b)', re.IGNORECASE)
_RE_EXCEPTION_SIMPLE = re.compile(r'EXCEPTION\s+WHEN\s+ERROR\s+THEN\s+SET\s+\w+\s*=\s*[\'"][^\'"]+[\'"]\s*;\s*END', re.IGNORECASE)
_RE_CTE_MATCH = re.compile(r'(\b[a-zA-Z0-9_]+)\s+AS\s*\(\s*SELECT', re.IGNORECASE)
_RE_TEMP_CREATE = re.compile(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY|TEMP)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)', re.IGNORECASE)
_RE_TEMP_DROP = re.compile(r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:TEMPORARY|TEMP\s+TABLE\s+)?([`\w\.\-]+)', re.IGNORECASE)
_RE_EXEC_DYNAMIC = re.compile(r'EXECUTE\s+IMMEDIATE', re.IGNORECASE)
_RE_EXEC_CONCAT = re.compile(r'(\'\'\s*\|\|\s*@|\+\s*@|CONCAT\(|\|\|)', re.IGNORECASE)

# Pilar 6: UDFs
_RE_JS_UDF = re.compile(r'LANGUAGE\s+js\b', re.IGNORECASE)

# Extracción de Tablas y Dependencias
_RE_FROM_TABLES = re.compile(r'\bFROM\s+([`\w\.\-]+)', re.IGNORECASE)
_RE_JOIN_TABLES = re.compile(r'\bJOIN\s+([`\w\.\-]+)', re.IGNORECASE)
_RE_CALL_STMT = re.compile(r'\bCALL\s+([`\w\.\-]+)', re.IGNORECASE)


def _remove_sql_comments(sql: str) -> str:
    sql = _RE_COMMENTS_BLOCK.sub('', sql)
    sql = _RE_COMMENTS_LINE.sub('', sql)
    return sql


def _clean_table_identifier(table_name: str) -> str:
    return table_name.strip("` \n\t;(),")


def _extract_dependencies(clean_sql: str) -> dict:
    cte_names = _RE_CTE_MATCH.findall(clean_sql)
    cte_set = {c.strip() for c in cte_names}

    call_matches = _RE_CALL_STMT.findall(clean_sql)
    stored_procedures = {_clean_table_identifier(sp) for sp in call_matches if sp.strip()}

    targets = set()
    create_tables = re.findall(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    insert_tables = re.findall(r'INSERT\s+(?:INTO\s+)?([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    update_tables = re.findall(r'UPDATE\s+([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    merge_tables = re.findall(r'MERGE\s+(?:INTO\s+)?([`\w\.\-]+)', clean_sql, re.IGNORECASE)

    for group in [create_tables, insert_tables, update_tables, merge_tables]:
        for tbl in group:
            cleaned = _clean_table_identifier(tbl)
            if cleaned and not cleaned.lower().startswith(("temporary", "temp")):
                targets.add(cleaned)

    temp_matches = _RE_TEMP_CREATE.findall(clean_sql)
    temp_tables = {_clean_table_identifier(tbl) for tbl in temp_matches}

    from_matches = _RE_FROM_TABLES.findall(clean_sql)
    join_matches = _RE_JOIN_TABLES.findall(clean_sql)
    
    sources = set()
    for tbl in from_matches + join_matches:
        cleaned = _clean_table_identifier(tbl)
        if cleaned and cleaned not in cte_set and cleaned not in temp_tables:
            if not cleaned.lower().startswith("unnest"):
                sources.add(cleaned)

    all_objects = []
    for sp in sorted(list(stored_procedures)):
        all_objects.append({"name": sp, "type": "Procedimiento Almacenado"})
    for tgt in sorted(list(targets)):
        all_objects.append({"name": tgt, "type": "Tabla"})
    for src in sorted(list(sources)):
        if src not in targets and src not in stored_procedures:
            all_objects.append({"name": src, "type": "Tabla / Vista"})

    return {
        "all_objects_detected": all_objects,
        "source_tables_and_views": sorted(list(sources)),
        "target_tables_and_views": sorted(list(targets)),
        "stored_procedures_called": sorted(list(stored_procedures)),
        "temporary_tables_created": sorted(list(temp_tables)),
        "ctes_defined": sorted(list(cte_set))
    }


def audit_sql_antipatterns_and_dependencies(sql_code: str) -> dict:
    if not sql_code or not sql_code.strip():
        return {"status": "error", "error_message": "Código SQL vacío."}

    clean_sql = _remove_sql_comments(sql_code)
    sql_no_strings = _RE_STRINGS.sub("''", clean_sql)

    detected = []

    # Pilar 1: I/O y Particiones
    if _RE_SELECT_STAR.search(clean_sql):
        detected.append({
            "pilar": "Pilar 1",
            "severity": "🔴 Alta",
            "id": "1.1",
            "name": "selectStar (Uso Indiscriminado de SELECT *)",
            "impact": "Fuerza lectura de columnas innecesarias en tabla columnar, multiplicando costos de escaneo.",
            "recommendation": "Proyectar explícitamente solo las columnas requeridas (SELECT col1, col2)."
        })

    if _RE_PART_FUNC.search(clean_sql):
        detected.append({
            "pilar": "Pilar 1",
            "severity": "🔴 Alta",
            "id": "1.12",
            "name": "partitionPruningDisabled (Deshabilitación de Poda de Particiones por Funciones)",
            "impact": "Usar funciones sobre columnas de partición en WHERE anula el partition pruning (Full Table Scan).",
            "recommendation": "Filtrar directamente sobre el campo de partición con rangos puros (>= y <)."
        })

    merge_match = _RE_MERGE_STMT.search(clean_sql)
    if merge_match:
        target_name, on_cond = merge_match.groups()
        if not re.search(r'\b(fecha|date|timestamp|periodo|anio|mes|dia)\b', on_cond, re.IGNORECASE):
            detected.append({
                "pilar": "Pilar 1",
                "severity": "🔴 Alta",
                "id": "1.18",
                "name": "unpartitionedMergeTarget (Escaneo Completo en MERGE Destino)",
                "impact": "Cláusula ON de MERGE sin filtro de partición destino, provocando escaneo histórico total.",
                "recommendation": "Incluir filtro explícito sobre la columna de partición de la tabla destino en la cláusula ON."
            })

    if _RE_ORDER_IN_CTE.search(clean_sql):
        detected.append({
            "pilar": "Pilar 1",
            "severity": "🟢 Baja",
            "id": "1.8",
            "name": "orderByWithoutLimit (Ordenamiento Masivo en CTEs Intermedias)",
            "impact": "Ordenar datos dentro de subconsultas o CTEs intermedias sin LIMIT desperdicia CPU y memoria en slots.",
            "recommendation": "Eliminar ORDER BY en subconsultas intermedias; ordenar únicamente en la consulta final."
        })

    # Pilar 2: Slots y Shuffle
    if _RE_IMPLICIT_JOIN.search(clean_sql):
        detected.append({
            "pilar": "Pilar 2",
            "severity": "🟡 Media",
            "id": "1.5",
            "name": "joinOrder (Cruces Implícitos no ANSI)",
            "impact": "Cruces en el WHERE mediante comas dificultan la optimización y pueden inducir productos cartesianos.",
            "recommendation": "Usar sintaxis ANSI estándar explícita (FROM t1 INNER JOIN t2 ON t1.id = t2.id)."
        })

    from_tables = _RE_FROM_TABLES.findall(clean_sql)
    join_tables = _RE_JOIN_TABLES.findall(clean_sql)
    all_sources = [_clean_table_identifier(t) for t in from_tables + join_tables]
    table_counts = {}
    for t in all_sources:
        if not t.lower().startswith("unnest"):
            table_counts[t] = table_counts.get(t, 0) + 1
    if any(count > 1 for count in table_counts.values()):
        detected.append({
            "pilar": "Pilar 2",
            "severity": "🔴 Alta",
            "id": "1.14",
            "name": "selfJoin (Uso de Self-JOINs)",
            "impact": "Unir una tabla consigo misma para comparar filas consecutivas duplica los bytes leídos y satura el shuffle.",
            "recommendation": "Usar funciones de ventana analíticas (LAG, LEAD, FIRST_VALUE)."
        })

    # Pilar 3: Eficiencia Analítica y Ventanas
    if _RE_ORDER_LIMIT1.search(clean_sql) and not _RE_OVER.search(clean_sql):
        detected.append({
            "pilar": "Pilar 3",
            "severity": "🔴 Alta",
            "id": "1.6",
            "name": "latestRecord (Obtención Ineficiente del Último Registro)",
            "impact": "ORDER BY col DESC LIMIT 1 fuerza un ordenamiento global en un único slot distribuidor.",
            "recommendation": "Usar funciones de ventana: QUALIFY ROW_NUMBER() OVER(PARTITION BY entidad_id ORDER BY fecha DESC) = 1."
        })

    # Pilar 4: Cadenas y Aritmética
    if _RE_UNSAFE_DIV.search(sql_no_strings) and not _RE_SAFE_DIV.search(sql_no_strings):
        detected.append({
            "pilar": "Pilar 4",
            "severity": "🟡 Media",
            "id": "1.11",
            "name": "whereOrder (División Insegura / División por Cero)",
            "impact": "Evaluación en paralelo sin orden secuencial garantizado causa fallos por división entre cero en runtime.",
            "recommendation": "Usar siempre SAFE_DIVIDE(a, b) o a / NULLIF(b, 0)."
        })

    if len(_RE_REPEATED_TIME_FUNC.findall(clean_sql)) > 1:
        detected.append({
            "pilar": "Pilar 4",
            "severity": "🟡 Media",
            "id": "1.26",
            "name": "timeFunctionMemoization (Reevaluación de Funciones de Tiempo)",
            "impact": "Invocaciones repetidas de funciones de tiempo calculan el mismo formato en múltiples sentencias.",
            "recommendation": "Memoizar el timestamp en una variable procedimental al inicio del bloque."
        })

    # Pilar 5: Procedimientos Almacenados (SPs)
    if _RE_EXCEPTION_SIMPLE.search(clean_sql):
        detected.append({
            "pilar": "Pilar 5",
            "severity": "🟡 Media",
            "id": "1.28",
            "name": "unhandledExceptionLogging (Omisión de Captura de Error en Excepciones)",
            "impact": "El bloque de excepción suprime el detalle del error sin capturar @@error.message, impidiendo depurar la causa raíz en las alertas.",
            "recommendation": "Capturar @@error.message en una variable procedimental (SET error_message = @@error.message;) para incluirla en la alerta."
        })

    if _RE_LOOPS.search(clean_sql):
        detected.append({
            "pilar": "Pilar 5",
            "severity": "🔴 Alta",
            "id": "1.27",
            "name": "iterativeRowByRow (Bucles Iterativos Fila por Fila)",
            "impact": "Uso de bucles en SPs anula el paralelismo MPP y degrada drásticamente el rendimiento.",
            "recommendation": "Vectorizar la lógica mediante operaciones DML masivas (MERGE, ARRAY_AGG + UNNEST)."
        })

    temp_created = {_clean_table_identifier(t) for t in _RE_TEMP_CREATE.findall(clean_sql)}
    temp_dropped = {_clean_table_identifier(t) for t in _RE_TEMP_DROP.findall(clean_sql)}
    missing_drops = temp_created - temp_dropped
    if missing_drops:
        detected.append({
            "pilar": "Pilar 5",
            "severity": "🟡 Media",
            "id": "1.2",
            "name": "missingDropStatement (Omisión de DROP TABLE en Tablas Temporales)",
            "impact": f"Tablas temporales creadas sin liberar ({', '.join(missing_drops)}), reteniendo recursos de sesión.",
            "recommendation": "Agregar siempre DROP TABLE IF EXISTS <tabla_temp>; al terminar el bloque."
        })

    dependencies = _extract_dependencies(clean_sql)

    return {
        "status": "success",
        "antipatterns_count": len(detected),
        "antipatterns": detected,
        "dependencies": dependencies
    }


# =====================================================================
# BLOQUE 4: DEFINICIÓN DEL AGENTE PRINCIPAL DE GOOGLE ADK (GOOGLE CHAT READY)
# =====================================================================

root_agent = Agent(
    name="agente_3",
    model="gemini-2.5-flash",
    description=(
        "Agente Orquestador Inviolable de Auditoría, Optimización SQL Determinista, FinOps, DataOps, MESH Standards "
        "y Mapeo de Dependencias (Sheets) en Google Cloud BigQuery."
    ),
    instruction=(
        "Eres el Agente Orquestador Inviolable de Auditoría y Optimización SQL en Google BigQuery y Arquitecto de Gobierno de Datos MESH.\n\n"
        "### 🛡️ BARRERAS DE SEGURIDAD Y ÁMBITO:\n"
        "- Tu propósito es orquestar la auditoría, optimización, mapeo de dependencias de código SQL en BigQuery y validación de nomenclatura MESH.\n"
        "- Si la entrada del usuario NO es código SQL, nombres de tablas ni temas relacionados con bases de datos ni saludos, responde ÚNICAMENTE:\n"
        "\"Solo estoy programado para asistir en temas de auditoría y optimización de bases de datos y SQL.\"\n\n"
        "------------------------------------------------------------------------------------\n"
        "### 🧠 EVALUACIÓN DE INTENCIÓN:\n\n"
        "📌 CASO 0: SALUDO, BIENVENIDA O CONSULTA GENERAL\n"
        "Si el usuario saluda (ej. 'hola', 'buenas tardes', 'buenos días', 'ayuda', 'qué puedes hacer'), responde EXACTAMENTE con:\n\n"
        "Hola, soy tu asistente experto en Gobierno de Datos, DataOps y FinOps en Google Cloud BigQuery.\n\n"
        "¿En qué puedo ayudarte hoy? Por ejemplo, puedes:\n"
        "• Validar la nomenclatura de una tabla, como 'stg_ventas_pos'.\n"
        "• Auditar y optimizar un código SQL o Stored Procedure.\n"
        "• Preguntar sobre buenas prácticas de optimización en BigQuery.\n\n"
        "Estoy aquí para ayudarte a asegurar que tus datos estén bien gobernados y tus consultas sean lo más eficientes posible.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 1: VALIDACIÓN EXCLUSIVA DE NOMENCLATURA DE TABLAS (Estándar MESH)\n"
        "Si el usuario proporciona nombres de tablas o consulta el estándar MESH:\n"
        "1. Ejecuta `validate_table_against_mesh_standard`.\n"
        "2. Responde indicando Veredicto, Regla Evaluada y Sugerencia de Corrección si no cumple.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 2: CÓDIGO SQL, QUERIES O PROCEDIMIENTOS (Auditoría y Optimización en Google Chat)\n"
        "1. Ejecuta OBLIGATORIAMENTE `audit_sql_antipatterns_and_dependencies` y `get_sql_optimization_rules_and_standards`.\n"
        "2. ⚠️ REGLAS DE DISEÑO PARA GOOGLE CHAT:\n"
        "   - PROHIBIDO USAR TABLAS DE MARKDOWN CON BARRAS (| col1 | col2 |).\n"
        "   - Usa tarjetas con viñetas limpias (•), negritas y sangrías ordenadas.\n"
        "   - Entrega las 3 secciones continuas en una ÚNICA respuesta monolítica.\n"
        "   - CERO CONVERSACIÓN al entregar el análisis de SQL (empieza directo en 'Análisis y optimización del script proporcionado:').\n"
        "   - ZERO-REGRESSION: Código 100% completo, sin truncar, garantizando paridad de resultados.\n\n"
        "### 📋 FORMATO DE SALIDA EXACTO Y ELEGANTE PARA GOOGLE CHAT:\n\n"
        "Análisis y optimización del script proporcionado:\n\n"
        "*🚨 1. Antipatrones y Malas Prácticas Detectadas*\n\n"
        "• *[🔴 Alta / 🟡 Media / 🟢 Baja] Pilar X - ID NombreAntipatrón*\n"
        "  - *Ubicación / Fragmento:* `fragmento_de_codigo`\n"
        "  - *Impacto / Riesgo:* [Explicación concisa del impacto en slots, bytes, memoria o depuración]\n"
        "  - *Sugerencia de Mejora:* [Solución recomendada]\n\n"
        "(Si no se detectaron antipatrones, escribe: '• *[🟢 Sin Hallazgos]* El código cumple con las buenas prácticas y estándares de optimización.')\n\n"
        "*🚀 2. Optimización del Código*\n\n"
        "```sql\n"
        "-- Código SQL / Procedimiento completamente optimizado y 100% ejecutable\n"
        "```\n\n"
        "*Puntos Clave de Optimización y Cumplimiento de Buenas Prácticas:*\n\n"
        "• *[Pilar X - ID NombreTécnica]:*\n"
        "  - *Antes:* `[Código original]`\n"
        "  - *Ahora:* `[Código refactorizado]`\n"
        "  - *Impacto / Beneficio Directo:* [Explicación técnica del beneficio]\n\n"
        "• *Garantía de Paridad Funcional:* Confirmación de que el flujo lógico, parámetros, destinatarios y esquema permanecen 100% idénticos para prueba inmediata con EXCEPT DISTINCT.\n\n"
        "*📊 3. Dependencias (Inventario de Tablas y Procedimientos Consultados)*\n\n"
        "• `nombre_tabla_o_procedimiento` (Tipo: Tabla / Vista / Procedimiento Almacenado)\n"
    ),
    tools=[
        audit_sql_antipatterns_and_dependencies,
        get_sql_optimization_rules_and_standards,
        validate_table_against_mesh_standard
    ]
)