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


# Obtiene la ruta base del paquete agente_3
BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "GD_Estándar de Nomenclatura_MESH.pdf"
GUIDE_PATH = BASE_DIR / "guia_antipatrones_bigquery.md"

# Caché en memoria para lectura ultra-rápida (0 ms)
_CACHED_PDF_TEXT: Optional[str] = None
_CACHED_GUIDE_TEXT: Optional[str] = None


def validate_table_against_mesh_standard(table_name: str) -> dict:
    """Lee el estándar de nomenclatura MESH desde el archivo PDF local y evalúa si el nombre de una tabla cumple las reglas.

    Args:
        table_name (str): El nombre de la tabla de BigQuery o Spark (ejemplo: 'stg_ventas_pos', 'cis_clientes_dim', 'fac_transacciones_his').

    Returns:
        dict: Estado de la lectura del archivo, contenido extraído del estándar y nombre de la tabla.
    """
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
            extracted = page.extract_text()
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


def get_sql_optimization_rules_and_standards(topic: str = "all") -> dict:
    """Obtiene el catálogo conciso de directrices de optimización columnar y FinOps en BigQuery."""
    global _CACHED_GUIDE_TEXT
    if _CACHED_GUIDE_TEXT is not None:
        return {
            "status": "success",
            "topic": topic,
            "rules": _CACHED_GUIDE_TEXT
        }

    _CACHED_GUIDE_TEXT = _get_fallback_guidelines()
    return {
        "status": "success",
        "topic": topic,
        "rules": _CACHED_GUIDE_TEXT
    }


def _get_fallback_guidelines() -> str:
    return (
        "1. Proyección Columnar: Evitar SELECT *, proyectar solo columnas requeridas.\n"
        "2. Poda de Particiones: Comparar directamente columnas de partición sin aplicarles funciones (DATE, CAST).\n"
        "3. Tablas Temporales: Usar CREATE TEMP TABLE en vez de CTEs repetidas; siempre liberar con DROP TABLE IF EXISTS.\n"
        "4. Cruces ANSI: Usar JOIN explícito con ON; filtrar claves nulas o comodines ('99999').\n"
        "5. División Segura: Usar SAFE_DIVIDE() o NULLIF(divisor, 0).\n"
        "6. Ventana/Deduplicación: Usar QUALIFY ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ... DESC) = 1.\n"
        "7. Agregación Condicional: Sustituir UNION ALL de la misma tabla por CASE WHEN + SUM/COUNTIF.\n"
        "8. Desanidado: Un solo CROSS JOIN UNNEST con COUNTIF en vez de múltiples UNNEST correlacionados."
    )


# Expresiones regulares precompiladas para máxima velocidad
_RE_COMMENTS_BLOCK = re.compile(r'/\*.*?\*/', re.DOTALL)
_RE_COMMENTS_LINE = re.compile(r'(--|#).*?$', re.MULTILINE)
_RE_SELECT_STAR = re.compile(r'\bSELECT\s+(?:DISTINCT\s+)?\*(?!\s*\w+\.)', re.IGNORECASE)
_RE_TEMP_CREATE = re.compile(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY|TEMP)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)', re.IGNORECASE)
_RE_TEMP_DROP = re.compile(r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:TEMPORARY|TEMP\s+TABLE\s+)?([`\w\.\-]+)', re.IGNORECASE)
_RE_EXEC_DYNAMIC = re.compile(r'EXECUTE\s+IMMEDIATE', re.IGNORECASE)
_RE_EXEC_CONCAT = re.compile(r'(\'\'\s*\|\|\s*@|\+\s*@|CONCAT\()', re.IGNORECASE)
_RE_IMPLICIT_JOIN = re.compile(r'FROM\s+[`\w\.\-]+(?:\s+(?:AS\s+)?[a-zA-Z0-9_]+)?\s*,\s*[`\w\.\-]+', re.IGNORECASE)
_RE_ORDER_LIMIT1 = re.compile(r'ORDER\s+BY\s+[`\w\.\-]+\s+DESC\s+LIMIT\s+1\b', re.IGNORECASE)
_RE_OVER = re.compile(r'OVER\s*\(', re.IGNORECASE)
_RE_CTE_MATCH = re.compile(r'(\b[a-zA-Z0-9_]+)\s+AS\s*\(\s*SELECT', re.IGNORECASE)
_RE_ORDER_IN_CTE = re.compile(r'WITH\s+.*ORDER\s+BY\s+[\w\.\,\s]+(?!\s+LIMIT\s+\d+)\s*\)', re.IGNORECASE | re.DOTALL)
_RE_SUBQUERY_IN = re.compile(r'WHERE\s+[`\w\.]+\s+IN\s*\(\s*SELECT\s+[`\w\.]+\s+FROM', re.IGNORECASE)
_RE_UNSAFE_DIV = re.compile(r'/\s*[`\w\.]+', re.IGNORECASE)
_RE_SAFE_DIV = re.compile(r'SAFE_DIVIDE|NULLIF', re.IGNORECASE)
_RE_PART_FUNC = re.compile(r'(?:DATE|DATETIME|TIMESTAMP|DATE_TRUNC|TIMESTAMP_TRUNC|CAST)\s*\(\s*[`\w\.]+\s*\)\s*(=|<|>|<=|>=|BETWEEN)', re.IGNORECASE)
_RE_JOIN_CLAUSE = re.compile(r'JOIN\s+([`\w\.\-]+)\s+(?:AS\s+)?(\w+)?\s*ON\s+([^;\n]+)', re.IGNORECASE)
_RE_SKEWED_CHECK = re.compile(r'IS\s+NOT\s+NULL|!=\s*[\'"]99999[\'"]|!=\s*[\'"]-1[\'"]', re.IGNORECASE)
_RE_FROM_TABLES = re.compile(r'\bFROM\s+([`\w\.\-]+)', re.IGNORECASE)
_RE_JOIN_TABLES = re.compile(r'\bJOIN\s+([`\w\.\-]+)', re.IGNORECASE)
_RE_PREMATURE_REGEXP = re.compile(r'WHERE\s+REGEXP_(?:CONTAINS|EXTRACT|REPLACE)\s*\(.*?\)\s+AND\s+[`\w\.]+\s*=', re.IGNORECASE | re.DOTALL)
_RE_UNION_ALL = re.compile(r'\bUNION\s+ALL\b', re.IGNORECASE)
_RE_MULTI_UNNEST = re.compile(r'\(\s*SELECT\s+.*?FROM\s+UNNEST\(', re.IGNORECASE)
_RE_WHERE_1_1 = re.compile(r'\bWHERE\s+1\s*=\s*1\b', re.IGNORECASE)


def _remove_sql_comments(sql: str) -> str:
    """Elimina comentarios de línea y de bloque de forma instantánea."""
    return _RE_COMMENTS_LINE.sub('', _RE_COMMENTS_BLOCK.sub('', sql))


def _clean_table_identifier(table_name: str) -> str:
    """Limpia caracteres de escape de un identificador de tabla."""
    return table_name.strip("` \n\t;()")


def _extract_dependencies(clean_sql: str) -> dict:
    """Extrae las dependencias de tablas de primer nivel (origen, destino, temporales y CTEs)."""
    # CTEs
    cte_names = _RE_CTE_MATCH.findall(clean_sql)
    cte_set = {c.strip() for c in cte_names}

    # Tablas destino
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

    # Tablas temporales creadas
    temp_matches = _RE_TEMP_CREATE.findall(clean_sql)
    temp_tables = {_clean_table_identifier(tbl) for tbl in temp_matches}

    # Tablas origen (FROM, JOIN)
    from_matches = _RE_FROM_TABLES.findall(clean_sql)
    join_matches = _RE_JOIN_TABLES.findall(clean_sql)
    
    sources = set()
    for tbl in from_matches + join_matches:
        cleaned = _clean_table_identifier(tbl)
        if cleaned and cleaned not in cte_set and cleaned not in temp_tables:
            if not cleaned.lower().startswith("unnest"):
                sources.add(cleaned)

    return {
        "source_tables_and_views": sorted(list(sources)),
        "target_tables_and_views": sorted(list(targets)),
        "temporary_tables_created": sorted(list(temp_tables)),
        "ctes_defined": sorted(list(cte_set))
    }


def audit_sql_antipatterns_and_dependencies(sql_code: str) -> dict:
    """Audita código SQL/SP para detectar antipatrones y extraer dependencias en milisegundos con salida compacta."""
    if not sql_code or not sql_code.strip():
        return {
            "status": "error",
            "error_message": "Código SQL vacío."
        }

    clean_sql = _remove_sql_comments(sql_code)
    detected = []

    # 1.1. selectStar
    if _RE_SELECT_STAR.search(clean_sql):
        detected.append({
            "id": "1.1",
            "name": "selectStar",
            "risk": "Fuerza escaneo completo de columnas en tabla columnar.",
            "recommendation": "Proyectar solo columnas indispensables."
        })

    # 1.2. missingDropStatement
    temp_created = {_clean_table_identifier(t) for t in _RE_TEMP_CREATE.findall(clean_sql)}
    temp_dropped = {_clean_table_identifier(t) for t in _RE_TEMP_DROP.findall(clean_sql)}
    missing_drops = temp_created - temp_dropped
    if missing_drops:
        detected.append({
            "id": "1.2",
            "name": "missingDropStatement",
            "risk": f"Tablas temporales sin liberar ({', '.join(missing_drops)}).",
            "recommendation": "Agregar DROP TABLE IF EXISTS al final."
        })

    # 1.4. dynamicPredicate
    if _RE_EXEC_DYNAMIC.search(clean_sql) and _RE_EXEC_CONCAT.search(clean_sql):
        detected.append({
            "id": "1.4",
            "name": "dynamicPredicate",
            "risk": "Filtros concatenados vulnerables y no optimizados.",
            "recommendation": "Usar parámetros tipados o cláusula USING."
        })

    # 1.5. joinOrder
    if _RE_IMPLICIT_JOIN.search(clean_sql):
        detected.append({
            "id": "1.5",
            "name": "joinOrder",
            "risk": "Cruces implícitos mediante comas.",
            "recommendation": "Usar sintaxis ANSI JOIN explícita (INNER/LEFT JOIN ... ON ...)."
        })

    # 1.6. latestRecord / QUALIFY
    if _RE_ORDER_LIMIT1.search(clean_sql) and not _RE_OVER.search(clean_sql):
        detected.append({
            "id": "1.6",
            "name": "latestRecord",
            "risk": "ORDER BY ... LIMIT 1 fuerza ordenamiento global en 1 slot.",
            "recommendation": "Usar QUALIFY ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ... DESC) = 1."
        })

    # 1.7. multipleCTES
    cte_matches = _RE_CTE_MATCH.findall(clean_sql)
    if len(cte_matches) >= 3:
        detected.append({
            "id": "1.7",
            "name": "multipleCTES",
            "risk": "Múltiples CTEs recalculadas en cada invocación.",
            "recommendation": "Materializar en CREATE TEMP TABLE si se reutilizan."
        })

    # 1.8. orderByWithoutLimit
    if _RE_ORDER_IN_CTE.search(clean_sql):
        detected.append({
            "id": "1.8",
            "name": "orderByWithoutLimit",
            "risk": "ORDER BY en CTEs intermedias satura memoria.",
            "recommendation": "Eliminar ORDER BY de las CTEs intermedias."
        })

    # 1.10. subqueryInFilterWithoutAgg
    if _RE_SUBQUERY_IN.search(clean_sql):
        detected.append({
            "id": "1.10",
            "name": "subqueryInFilterWithoutAgg",
            "risk": "Subconsulta WHERE IN en vez de JOIN.",
            "recommendation": "Reemplazar por INNER JOIN o WHERE EXISTS."
        })

    # 1.11. whereOrder / Unsafe Division
    if _RE_UNSAFE_DIV.search(clean_sql) and not _RE_SAFE_DIV.search(clean_sql):
        detected.append({
            "id": "1.11",
            "name": "whereOrder (Unsafe Division)",
            "risk": "División sin protección contra cero.",
            "recommendation": "Usar SAFE_DIVIDE(dividendo, divisor)."
        })

    # 1.12. partitionPruningDisabled
    if _RE_PART_FUNC.search(clean_sql):
        detected.append({
            "id": "1.12",
            "name": "partitionPruningDisabled",
            "risk": "Funciones sobre columnas particionadas anulan la poda (Full Scan).",
            "recommendation": "Comparar directamente la columna de partición con el literal de fecha."
        })

    # 1.13. skewedJoinKeys
    join_matches = _RE_JOIN_CLAUSE.findall(clean_sql)
    for target_tbl, alias, condition in join_matches:
        if not _RE_SKEWED_CHECK.search(condition):
            detected.append({
                "id": "1.13",
                "name": "skewedJoinKeys",
                "risk": "Cruces sobre posibles llaves nulas o comodines ('99999').",
                "recommendation": "Filtrar IS NOT NULL en llaves de unión."
            })
            break

    # 1.14. selfJoin
    from_tables = _RE_FROM_TABLES.findall(clean_sql)
    join_tables = _RE_JOIN_TABLES.findall(clean_sql)
    all_sources = [_clean_table_identifier(t) for t in from_tables + join_tables]
    table_counts = {}
    for t in all_sources:
        if not t.lower().startswith("unnest"):
            table_counts[t] = table_counts.get(t, 0) + 1
    if any(count > 1 for count in table_counts.values()):
        detected.append({
            "id": "1.14",
            "name": "selfJoin",
            "risk": "Self-JOIN duplica lectura de almacenamiento.",
            "recommendation": "Usar funciones de ventana (LAG, LEAD, ROW_NUMBER)."
        })

    # 1.15. prematureRegexp
    if _RE_PREMATURE_REGEXP.search(clean_sql):
        detected.append({
            "id": "1.15",
            "name": "prematureRegexp",
            "risk": "REGEXP evaluado antes de filtros simples.",
            "recommendation": "Colocar filtros escalares primero y REGEXP al final."
        })

    # 1.16. redundantUnionAll
    if len(_RE_UNION_ALL.findall(clean_sql)) >= 1 and any(count > 1 for count in table_counts.values()):
        detected.append({
            "id": "1.16",
            "name": "redundantUnionAll",
            "risk": "UNION ALL repetitivo sobre la misma tabla.",
            "recommendation": "Consolidar en una sola lectura con CASE WHEN + agregaciones."
        })

    # 1.17. multipleUnnests
    if len(_RE_MULTI_UNNEST.findall(clean_sql)) > 1:
        detected.append({
            "id": "1.17",
            "name": "multipleUnnests",
            "risk": "Múltiples UNNEST independientes disparan cómputo.",
            "recommendation": "Un solo CROSS JOIN UNNEST con COUNTIF."
        })

    # Antipatrón adicional: Cláusula estática WHERE 1=1
    if _RE_WHERE_1_1.search(clean_sql):
        detected.append({
            "id": "Extra",
            "name": "staticWherePredicate (WHERE 1=1 innecesario)",
            "risk": "Predicado estático redundante en consultas no dinámicas.",
            "recommendation": "Eliminar WHERE 1=1 y comenzar directamente con los filtros reales."
        })

    dependencies = _extract_dependencies(clean_sql)

    return {
        "status": "success",
        "antipatterns_count": len(detected),
        "antipatterns": detected,
        "dependencies": dependencies
    }


def _remove_sql_comments(sql: str) -> str:
    """Elimina comentarios de línea (-- o #) y de bloque (/* ... */) de una consulta SQL."""
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    sql = re.sub(r'(--|#).*?$', '', sql, flags=re.MULTILINE)
    return sql


def _clean_table_identifier(table_name: str) -> str:
    """Limpia caracteres de escape como backticks y espacios."""
    return table_name.strip("` \n\t;()")


def _extract_dependencies(clean_sql: str) -> dict:
    """Extrae las dependencias de tablas de origen, tablas de destino, tablas temporales y CTEs de primer nivel."""
    
    # CTEs
    cte_names = re.findall(r'(\b[a-zA-Z0-9_]+)\s+AS\s*\(\s*SELECT', clean_sql, re.IGNORECASE)
    cte_set = {c.strip() for c in cte_names}

    # Tablas destino (DML/DDL)
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

    # Tablas temporales creadas
    temp_tables = set()
    temp_matches = re.findall(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY|TEMP)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    for tbl in temp_matches:
        temp_tables.add(_clean_table_identifier(tbl))

    # Tablas origen (FROM, JOIN)
    from_matches = re.findall(r'\bFROM\s+([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    join_matches = re.findall(r'\bJOIN\s+([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    
    sources = set()
    for tbl in from_matches + join_matches:
        cleaned = _clean_table_identifier(tbl)
        # Excluir CTEs, tablas temporales del script y palabras clave
        if cleaned and cleaned not in cte_set and cleaned not in temp_tables:
            if not cleaned.lower().startswith("unnest"):
                sources.add(cleaned)

    return {
        "source_tables_and_views": sorted(list(sources)),
        "target_tables_and_views": sorted(list(targets)),
        "temporary_tables_created": sorted(list(temp_tables)),
        "ctes_defined": sorted(list(cte_set))
    }


# Definición del Agente Experto en Gobierno de Datos y Optimización BigQuery (Ultra Rápido)
root_agent = Agent(
    name="agente_3",
    model="gemini-2.5-flash",
    description=(
        "Agente Experto en Gobierno de Datos, FinOps, DataOps, MESH Standards y "
        "Optimización de Consultas, Scripts y Stored Procedures en Google Cloud BigQuery."
    ),
    instruction=(
        "Eres el Arquitecto Líder de Gobierno de Datos, DataOps y FinOps en Google Cloud BigQuery.\n"
        "Tu objetivo es asistir al usuario evaluando nomenclaturas bajo el estándar MESH, auditando y generando código SQL / Stored Procedures altamente optimizado.\n\n"
        "### 🧠 CLASIFICACIÓN DE INTENCIÓN DEL USUARIO:\n"
        "Evalúa primero la entrada del usuario para determinar el tipo de solicitud:\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 1: PREGUNTA O VALIDACIÓN DE NOMENCLATURA DE TABLAS (Estándar MESH)\n"
        "Si el usuario te proporciona uno o varios nombres de tablas (ej. 'stg_ventas_pos', 'tb_clientes', 'fac_facturacion_diaria'), o te hace una pregunta directa sobre si una tabla cumple el estándar:\n"
        "1. Ejecuta la herramienta `validate_table_against_mesh_standard` pasando el nombre de la tabla.\n"
        "2. Analiza las reglas contenidas en `mesh_standard_rules` (extraídas del estándar oficial en PDF).\n"
        "3. Responde de forma clara y estructurada indicando:\n"
        "   - Veredicto: Si la tabla cumple o no con la nomenclatura MESH.\n"
        "   - Regla Evaluada: Capa de datos (RAW, STG, CIS, FAC, DIM, etc.), prefijos, estructura de nombres, separadores y sufijos permitidos.\n"
        "   - 💡 Sugerencia de Corrección: Si no cumple, proporciona el nombre corregido sugerido según el estándar MESH.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 2: CÓDIGO SQL, SCRIPT, CONSULTA O STORED PROCEDURE (Auditoría y Optimización Ultra Rápida)\n"
        "Si el usuario te proporciona código SQL, un Stored Procedure (SP), Script DDL/DML o una consulta compleja:\n"
        "1. Auditoría de Antipatrones y Dependencias: Ejecuta `audit_sql_antipatterns_and_dependencies` para escanear el código contra el catálogo de 17 antipatrones de BigQuery y extraer todas las dependencias de tablas y vistas.\n"
        "2. Consulta de Buenas Prácticas: Ejecuta `get_sql_optimization_rules_and_standards` si requieres contrastar directrices de optimización columnar y FinOps.\n"
        "3. Validación MESH de Tablas: Invoca `validate_table_against_mesh_standard` sobre las tablas fuente o destino detectadas en el código.\n"
        "4. Estructura Obligatoria de Respuesta:\n"
        "   - 📊 1. Diagnóstico de Antipatrones y FinOps: Detalla cada antipatrón encontrado, dónde ocurre, el riesgo financiero (bytes escaneados) y de rendimiento (slots/CPU).\n"
        "   - 🔍 2. Dependencias Detectadas y Validación MESH: Lista de tablas fuente, destino, temporales y CTEs, junto con su validación de nomenclatura MESH.\n"
        "   - 🏗️ 3. Recomendaciones Arquitectónicas Específicas:\n"
        "     * Si el código contiene SELECT *, indicar la proyección de columnas indispensables.\n"
        "     * Recomendación de Particionamiento y Clusterización para las tablas de mayor volumen.\n"
        "     * Oportunidades de Vistas Materializadas para agregaciones recurrentes.\n"
        "   - ⚡ 4. Código SQL / Stored Procedure Optimizado: Bloque completo de código refactorizado y formateado aplicando las mejores prácticas (proyección explícita, cruces ANSI explícitos, SAFE_DIVIDE, funciones analíticas de ventana, tablas temporales con DROP explícito).\n"
        "   - 🛠️ 5. Desglose de Mejoras Aplicadas: Explicación técnica paso a paso de los beneficios obtenidos en costo y velocidad de respuesta.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 3: PREGUNTAS GENERALES O CONCEPTUALES DE BUENAS PRÁCTICAS\n"
        "Si el usuario pregunta por conceptos o recomendaciones generales de BigQuery, invoca `get_sql_optimization_rules_and_standards` o `validate_table_against_mesh_standard` y responde con precisión técnica citando las directrices."
    ),
    tools=[
        audit_sql_antipatterns_and_dependencies,
        get_sql_optimization_rules_and_standards,
        validate_table_against_mesh_standard
    ]
)
