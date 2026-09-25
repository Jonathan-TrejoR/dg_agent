import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from google.cloud import bigquery
except ImportError:
    bigquery = None

try:
    from google.adk.agents import Agent
except ImportError:
    class Agent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


# Obtiene la ruta base del paquete agent_dg2
BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "GD_Estándar de Nomenclatura_MESH.pdf"
GUIDE_PATH = BASE_DIR / "guia_antipatrones_bigquery.md"


def validate_table_against_mesh_standard(table_name: str) -> dict:
    """Lee el estándar de nomenclatura MESH desde el archivo PDF local y evalúa si el nombre de una tabla cumple las reglas.

    Args:
        table_name (str): El nombre de la tabla de BigQuery o Spark (ejemplo: 'stg_ventas_pos', 'cis_clientes_dim', 'fac_transacciones_his').

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

        return {
            "status": "success",
            "table_to_validate": table_name,
            "mesh_standard_rules": pdf_text
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"Error al leer el archivo PDF: {str(e)}"
        }


def get_sql_optimization_rules_and_standards(topic: str = "all") -> dict:
    """Obtiene el catálogo unificado de buenas prácticas y patrones de optimización para BigQuery (Queries, Stored Procedures, Scripts).

    Args:
        topic (str, optional): Tema específico a consultar ('all', 'antipatterns', 'storage', 'performance', 'procedures', 'cost'). Por defecto 'all'.

    Returns:
        dict: Contenido de la guía unificada de optimización, principios de arquitectura columnar y recomendaciones oficiales.
    """
    guide_file = Path(GUIDE_PATH)
    if guide_file.exists():
        try:
            with open(guide_file, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "status": "success",
                "topic": topic,
                "guide_content": content,
                "summary": "Guía cargada exitosamente desde guia_antipatrones_bigquery.md"
            }
        except Exception as e:
            return {
                "status": "warning",
                "error_message": f"No se pudo leer el archivo local: {str(e)}",
                "fallback_guidelines": _get_fallback_guidelines()
            }
    else:
        return {
            "status": "success",
            "topic": topic,
            "guide_content": _get_fallback_guidelines()
        }


def _get_fallback_guidelines() -> str:
    return """
    Principios Clave BigQuery:
    1. Arquitectura Columnar: Evitar SELECT *, proyectar solo columnas indispensables.
    2. Filtrado y Poda de Particiones: No aplicar funciones (DATE(), CAST()) sobre columnas de partición.
    3. Tablas Temporales: Usar CREATE TEMP TABLE en vez de CTEs repetidas; siempre liberar con DROP TABLE.
    4. Cruces ANSI: Usar JOIN explícito con ON; filtrar claves desbalanceadas (NULL o valores dummy).
    5. División Segura: Usar SAFE_DIVIDE() o NULLIF(divisor, 0) para prevenir errores de orden en WHERE.
    6. Funciones de Ventana: Usar ROW_NUMBER() / LAG() / LEAD() en lugar de Self-JOINs o LIMIT 1 no deterministas.
    7. Agregación Condicional: Sustituir UNION ALL de la misma tabla por CASE WHEN + SUM/COUNTIF.
    8. Desanidado Eficiente: Evitar subconsultas repetidas con UNNEST(); usar CROSS JOIN UNNEST con COUNTIF.
    9. Vistas Materializadas: Usar vistas materializadas para pre-agregar consultas masivas recurrentes.
    10. Clustering y Particionado: Particionar por tiempo/rango y clusterizar por llaves frecuentes de filtro y JOIN.
    """


def get_bigquery_tables_metadata(table_names: Any, max_depth: int = 5) -> dict:
    """Consulta los metadatos reales de tablas y vistas en BigQuery (esquema de columnas, tipos, descripciones de negocio, particionamiento, clústeres y volumen) limitado a las dependencias detectadas, resolviendo recursivamente cadenas de vistas anidadas hasta llegar a las tablas base físicas.

    Args:
        table_names (list | str): Nombre de una tabla o lista de nombres de tablas/vistas (ej. 'proyecto.dataset.ventas', ['dataset.vista_clientes', 'dataset.transacciones']).
        max_depth (int, optional): Profundidad máxima de recursión para rastrear vistas dependientes. Por defecto 5.

    Returns:
        dict: Metadatos detallados de cada tabla/vista directa e indirecta, árbol de linaje recursivo (cadenas de vistas hasta tablas base), identificación de tablas físicas subyacentes y recomendaciones arquitectónicas para optimización.
    """
    if bigquery is None:
        return {
            "status": "error",
            "error_message": "La librería 'google-cloud-bigquery' no está disponible en el entorno."
        }

    if isinstance(table_names, str):
        raw_list = [t.strip("` \n\t;()") for t in table_names.split(",") if t.strip()]
    elif isinstance(table_names, list):
        raw_list = [_clean_table_identifier(str(t)) for t in table_names if t]
    else:
        raw_list = []

    if not raw_list:
        return {
            "status": "error",
            "error_message": "No se proporcionaron nombres de tablas válidos para consultar en BigQuery."
        }

    try:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION")
        client = bigquery.Client(project=project_id, location=location) if project_id else bigquery.Client()
    except Exception as e:
        return {
            "status": "warning",
            "error_message": f"No se pudo inicializar la conexión con BigQuery: {str(e)}",
            "note": "Asegúrate de contar con credenciales activas en el entorno (gcloud auth application-default login)."
        }

    tables_metadata = []
    architectural_recommendations = []
    
    # Estructuras para resolución recursiva de linaje
    to_visit = []
    for t in raw_list:
        to_visit.append((t, 0, []))  # (table_id, current_depth, lineage_path)
    
    visited: Set[str] = set()
    lineage_chains: List[str] = []
    physical_base_tables: Set[str] = set()
    nested_views: Set[str] = set()

    while to_visit:
        tbl_id, depth, path = to_visit.pop(0)
        
        # Normalizar identificador
        full_table_id = tbl_id
        if "." in tbl_id and tbl_id.count(".") == 1 and client.project:
            full_table_id = f"{client.project}.{tbl_id}"

        if full_table_id in visited:
            continue
        visited.add(full_table_id)

        current_path = path + [full_table_id]

        try:
            table = client.get_table(full_table_id)
            is_view = table.table_type in ("VIEW", "MATERIALIZED_VIEW")
            
            # Esquema de columnas y descripciones de negocio
            columns_info = []
            for field in table.schema:
                columns_info.append({
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or "Sin descripción registrada"
                })

            # Particionamiento
            part_info = None
            if table.time_partitioning:
                part_info = {
                    "type": str(table.time_partitioning.type_),
                    "field": table.time_partitioning.field or "_PARTITIONDATE",
                    "expiration_ms": table.time_partitioning.expiration_ms
                }
            elif table.range_partitioning:
                part_info = {
                    "type": "RANGE",
                    "field": table.range_partitioning.field,
                    "range": f"Start: {table.range_partitioning.range_.start}, End: {table.range_partitioning.range_.end}, Interval: {table.range_partitioning.range_.interval}"
                }

            # Clústeres
            clusters = table.clustering_fields or []

            # Volumen y peso
            num_rows = table.num_rows
            num_bytes = table.num_bytes
            size_mb = round(num_bytes / (1024 * 1024), 2) if num_bytes else 0.0

            # Extracción recursiva si es Vista
            underlying_dependencies = []
            view_query_sql = None

            if is_view:
                nested_views.add(full_table_id)
                view_query_sql = getattr(table, "view_query", None)
                if not view_query_sql and hasattr(table, "materialized_view"):
                    view_query_sql = getattr(table.materialized_view, "query", None)

                if view_query_sql and depth < max_depth:
                    # Extraer dependencias de la consulta de la vista
                    view_deps = _extract_dependencies(view_query_sql)
                    referenced_sources = view_deps.get("source_tables_and_views", [])
                    underlying_dependencies = referenced_sources

                    for child in referenced_sources:
                        child_clean = _clean_table_identifier(child)
                        if "." in child_clean and child_clean.count(".") == 1 and client.project:
                            child_clean = f"{client.project}.{child_clean}"
                        
                        if child_clean not in visited:
                            to_visit.append((child_clean, depth + 1, current_path))
                elif not view_query_sql or depth >= max_depth:
                    lineage_chains.append(" -> ".join(current_path))
            else:
                physical_base_tables.add(full_table_id)
                if len(current_path) > 1:
                    lineage_chains.append(" -> ".join(current_path))

            table_meta = {
                "table_id": full_table_id,
                "table_type": table.table_type,
                "depth_level": depth,
                "is_direct_dependency": (depth == 0),
                "lineage_path": current_path,
                "num_rows": num_rows,
                "num_bytes": num_bytes,
                "size_mb": size_mb,
                "partitioning": part_info,
                "clustering_fields": clusters,
                "columns": columns_info,
                "underlying_dependencies": underlying_dependencies
            }
            tables_metadata.append(table_meta)

            # Diagnóstico de mejores prácticas de almacenamiento y respuesta
            if table.table_type == "TABLE":
                if not part_info and num_rows and num_rows > 100000:
                    architectural_recommendations.append({
                        "table": full_table_id,
                        "type": "SE_REQUIERE_PARTICIONAMIENTO",
                        "recommendation": f"Se requiere hacer particionamiento de la tabla base '{full_table_id}' ({num_rows:,} filas, {size_mb} MB) sobre la columna de fecha/timestamp principal para que las vistas y consultas superiores puedan podar particiones."
                    })
                if not clusters and num_rows and num_rows > 50000:
                    architectural_recommendations.append({
                        "table": full_table_id,
                        "type": "SE_REQUIERE_CLUSTERIZACION",
                        "recommendation": f"Se requiere clusterizar la tabla base '{full_table_id}' por las columnas de mayor filtrado o cruce (JOIN keys) para acelerar tiempos de respuesta."
                    })
            elif table.table_type == "VIEW":
                if depth > 1:
                    architectural_recommendations.append({
                        "table": full_table_id,
                        "type": "CADENA_DE_VISTAS_ANIDADAS",
                        "recommendation": f"Se detectó una cadena de vistas anidadas ({' -> '.join(current_path)}). Cada nivel intermedio suma latencia de compilación. Evaluar consolidar o crear una Vista Materializada en el nivel intermedio más consultado."
                    })
                else:
                    architectural_recommendations.append({
                        "table": full_table_id,
                        "type": "VISTA_MATERIALIZADA_RECOMENDADA",
                        "recommendation": f"Para no procesar datos masivos repetidamente desde la vista '{full_table_id}', se recomienda materializar el cálculo mediante una Vista Materializada (CREATE MATERIALIZED VIEW)."
                    })

        except Exception as e:
            tables_metadata.append({
                "table_id": full_table_id,
                "status": "error_fetching",
                "depth_level": depth,
                "lineage_path": current_path,
                "error": str(e)
            })

    return {
        "status": "success",
        "total_objects_evaluated": len(tables_metadata),
        "direct_dependencies_count": len(raw_list),
        "nested_views_detected": sorted(list(nested_views)),
        "physical_base_tables_detected": sorted(list(physical_base_tables)),
        "lineage_chains": sorted(list(set(lineage_chains))) if lineage_chains else [f"{t} (Tabla directa)" for t in raw_list],
        "tables_metadata": tables_metadata,
        "architectural_recommendations": architectural_recommendations
    }


def audit_sql_antipatterns_and_dependencies(sql_code: str) -> dict:
    """Analiza código SQL, Stored Procedures (SP) o Scripts de BigQuery para detectar antipatrones y extraer dependencias de tablas y vistas.

    Args:
        sql_code (str): Consulta SQL, Stored Procedure, Script o DDL/DML a auditar.

    Returns:
        dict: Reporte estructurado con lista de antipatrones detectados, severidad, explicación, dependencias (tablas fuente, tablas destino, tablas temporales, CTEs) y recomendaciones.
    """
    if not sql_code or not sql_code.strip():
        return {
            "status": "error",
            "error_message": "El código SQL proporcionado está vacío."
        }

    clean_sql = _remove_sql_comments(sql_code)
    detected_antipatterns = []
    
    # 1.1. selectStar
    if re.search(r'\bSELECT\s+(?:DISTINCT\s+)?\*(?!\s*\w+\.)', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.1",
            "name": "selectStar (Uso Indiscriminado de SELECT *)",
            "risk": "Fuerza el escaneo de todas las columnas en la tabla columnar, aumentando costos y tiempo de CPU.",
            "recommendation": "Seleccionar explícitamente solo las columnas requeridas (SELECT col1, col2...)."
        })

    # 1.2. missingDropStatement
    temp_tables_created = re.findall(
        r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY|TEMP)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)',
        clean_sql,
        re.IGNORECASE
    )
    temp_tables_dropped = re.findall(
        r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:TEMPORARY|TEMP\s+TABLE\s+)?([`\w\.\-]+)',
        clean_sql,
        re.IGNORECASE
    )
    clean_created_temps = {_clean_table_identifier(t) for t in temp_tables_created}
    clean_dropped_temps = {_clean_table_identifier(t) for t in temp_tables_dropped}
    missing_drops = clean_created_temps - clean_dropped_temps
    if missing_drops:
        detected_antipatterns.append({
            "id": "1.2",
            "name": "missingDropStatement (Omisión de DROP TABLE en Tablas Temporales)",
            "risk": f"Tablas temporales sin liberar ({', '.join(missing_drops)}) consumen recursos en la sesión hasta expirar.",
            "recommendation": "Agregar 'DROP TABLE <tabla_temp>;' al finalizar el procesamiento."
        })

    # 1.3. droppedPersistentTable
    persistent_created = re.findall(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w\.\-]+)',
        clean_sql,
        re.IGNORECASE
    )
    for p_table in persistent_created:
        clean_p = _clean_table_identifier(p_table)
        if clean_p in clean_dropped_temps and not clean_p.lower().startswith(("temp_", "tmp_", "_session")):
            detected_antipatterns.append({
                "id": "1.3",
                "name": "droppedPersistentTable (Uso de Tablas Persistentes como Temporales)",
                "risk": f"Crear y borrar repetidamente la tabla física '{clean_p}' en procesos batch satura los metadatos de GCP.",
                "recommendation": "Utilizar 'CREATE TEMP TABLE' o realizar 'INSERT INTO' / 'MERGE' en tablas persistentes consolidadas."
            })

    # 1.4. dynamicPredicate
    if re.search(r'EXECUTE\s+IMMEDIATE', clean_sql, re.IGNORECASE) and re.search(r'(\'\'\s*\|\|\s*@|\+\s*@|CONCAT\()', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.4",
            "name": "dynamicPredicate (Construcción Dinámica de Filtros por Concatenación)",
            "risk": "Vulnerabilidad a inyección SQL e imposibilidad de precompilar y optimizar el plan de ejecución.",
            "recommendation": "Usar parámetros SQL tipados directamente en consultas estáticas o con cláusula USING en EXECUTE IMMEDIATE."
        })

    # 1.5. joinOrder (Implicit cross/where joins)
    if re.search(r'FROM\s+[`\w\.\-]+(?:\s+(?:AS\s+)?[a-zA-Z0-9_]+)?\s*,\s*[`\w\.\-]+', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.5",
            "name": "joinOrder (Cruces Implícitos mediante Comas sin Sintaxis ANSI JOIN)",
            "risk": "Dificulta la optimización del plan de ejecución del motor y reduce la legibilidad del código.",
            "recommendation": "Reescribir usando sintaxis ANSI JOIN explícita (e.g., JOIN ... ON ...)."
        })

    # 1.6. latestRecord
    if re.search(r'ORDER\s+BY\s+[`\w\.\-]+\s+DESC\s+LIMIT\s+1\b', clean_sql, re.IGNORECASE) and not re.search(r'OVER\s*\(', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.6",
            "name": "latestRecord (Obtención Ineficiente del Último Registro con ORDER BY ... LIMIT 1)",
            "risk": "Fuerza un ordenamiento global de toda la tabla en un único slot/nodo distribuidor.",
            "recommendation": "Utilizar funciones de ventana: ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ... DESC) y filtrar WHERE rn = 1."
        })

    # 1.7. multipleCTES
    cte_matches = re.findall(r'(\w+)\s+AS\s*\(\s*SELECT', clean_sql, re.IGNORECASE)
    if len(cte_matches) >= 3:
        cte_multi_ref = False
        for cte in cte_matches:
            occurrences = len(re.findall(r'\b' + re.escape(cte) + r'\b', clean_sql, re.IGNORECASE))
            if occurrences > 2:
                cte_multi_ref = True
                break
        if cte_multi_ref or len(cte_matches) >= 4:
            detected_antipatterns.append({
                "id": "1.7",
                "name": "multipleCTES (Exceso de CTEs Fragmentadas o Re-ejecutadas)",
                "risk": "Los bloques WITH (CTE) no se materializan por defecto y se vuelven a ejecutar cada vez que se invocan.",
                "recommendation": "Materializar resultados intermedios en 'CREATE OR REPLACE TEMP TABLE' con partición o indexación."
            })

    # 1.8. orderByWithoutLimit
    if re.search(r'WITH\s+.*ORDER\s+BY\s+[\w\.\,\s]+(?!\s+LIMIT\s+\d+)\s*\)', clean_sql, re.IGNORECASE | re.DOTALL):
        detected_antipatterns.append({
            "id": "1.8",
            "name": "orderByWithoutLimit (Ordenamiento Masivo en CTEs Intermedias sin LIMIT)",
            "risk": "Satura la memoria intermedia del nodo distribuidor ordenando registros que luego serán transformados.",
            "recommendation": "Eliminar el ORDER BY de las CTEs intermedias y aplicar ordenamiento únicamente en la consulta final con LIMIT."
        })

    # 1.9. stringComparison
    if re.search(r'(?:WHERE|AND|OR|ON)\s+[`\w\.]+\s*=\s*[\'"][^\'"]+[\'"]', clean_sql, re.IGNORECASE) and not re.search(r'LOWER\(|UPPER\(|COLLATE\(', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.9",
            "name": "stringComparison (Comparación de Cadenas sin Colación o Normalización Explícita)",
            "risk": "Posibles inconsistencias en filtros por sensibilidad a mayúsculas/minúsculas y dependencia de colación.",
            "recommendation": "Normalizar explícitamente las cadenas comparadas usando LOWER(col) = LOWER('valor')."
        })

    # 1.10. subqueryInFilterWithoutAgg
    if re.search(r'WHERE\s+[`\w\.]+\s+IN\s*\(\s*SELECT\s+[`\w\.]+\s+FROM', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.10",
            "name": "subqueryInFilterWithoutAgg (Subconsulta en Filtro WHERE IN en lugar de JOIN)",
            "risk": "Inhibe la paralelización eficiente y puede generar planes de ejecución subóptimos.",
            "recommendation": "Reemplazar la subconsulta en WHERE IN por un INNER JOIN o EXISTS estructurado."
        })

    # 1.11. whereOrder / Unsafe Division
    if re.search(r'/\s*[`\w\.]+(?:\s*[+\-*/]\s*[`\w\.]+)?\s*(?:<|>|=|<=|>=|!=)', clean_sql, re.IGNORECASE) or \
       (re.search(r'/\s*[`\w\.]+', clean_sql) and not re.search(r'SAFE_DIVIDE|NULLIF', clean_sql, re.IGNORECASE)):
        detected_antipatterns.append({
            "id": "1.11",
            "name": "whereOrder (División Insegura / Dependencia del Orden de Evaluación)",
            "risk": "BigQuery no garantiza el orden de evaluación de predicados en el WHERE, pudiendo provocar fallos por división por cero.",
            "recommendation": "Utilizar SAFE_DIVIDE(dividendo, divisor) o NULLIF(divisor, 0)."
        })

    # 1.12. partitionPruningDisabled
    if re.search(r'(?:DATE|DATETIME|TIMESTAMP|DATE_TRUNC|TIMESTAMP_TRUNC|CAST)\s*\(\s*[`\w\.]+\s*\)\s*(=|<|>|<=|>=|BETWEEN)', clean_sql, re.IGNORECASE):
        detected_antipatterns.append({
            "id": "1.12",
            "name": "partitionPruningDisabled (Deshabilitación de Poda de Particiones por Uso de Funciones)",
            "risk": "Aplicar funciones sobre columnas particionadas en el filtro impide a BigQuery podar particiones, forzando un FULL TABLE SCAN.",
            "recommendation": "Comparar directamente la columna de partición contra el literal de fecha (ej. fecha_registro = '2026-06-13')."
        })

    # 1.13. skewedJoinKeys
    join_matches = re.findall(r'JOIN\s+([`\w\.\-]+)\s+(?:AS\s+)?(\w+)?\s*ON\s+([^;\n]+)', clean_sql, re.IGNORECASE)
    for target_tbl, alias, condition in join_matches:
        if not re.search(r'IS\s+NOT\s+NULL|!=\s*[\'"]99999[\'"]|!=\s*[\'"]-1[\'"]', clean_sql, re.IGNORECASE):
            detected_antipatterns.append({
                "id": "1.13",
                "name": "skewedJoinKeys (Cruces Ineficientes sobre Datos Desbalanceados / Skewed Keys)",
                "risk": "Valores nulos o comodines masivos ('99999', NULL) en llaves de unión sobrecargan un único slot distribuidor.",
                "recommendation": "Filtrar previamente valores nulos o comodines en las llaves de cruce (WHERE llave IS NOT NULL AND llave != '99999')."
            })
            break

    # 1.14. selfJoin
    from_tables = re.findall(r'FROM\s+([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    join_tables = re.findall(r'JOIN\s+([`\w\.\-]+)', clean_sql, re.IGNORECASE)
    all_sources = [_clean_table_identifier(t) for t in from_tables + join_tables]
    table_counts = {}
    for t in all_sources:
        if not t.lower().startswith("unnest"):
            table_counts[t] = table_counts.get(t, 0) + 1
    if any(count > 1 for count in table_counts.values()):
        detected_antipatterns.append({
            "id": "1.14",
            "name": "selfJoin (Uso de Self-JOINs en Lugar de Funciones Analíticas de Ventana)",
            "risk": "Realizar JOIN de una tabla contra sí misma duplica innecesariamente los bytes leídos de almacenamiento.",
            "recommendation": "Reemplazar el Self-JOIN por funciones analíticas de ventana como LAG(), LEAD(), FIRST_VALUE() o SUM() OVER()."
        })

    # 1.15. prematureRegexp
    if re.search(r'WHERE\s+REGEXP_(?:CONTAINS|EXTRACT|REPLACE)\s*\(.*?\)\s+AND\s+[`\w\.]+\s*=', clean_sql, re.IGNORECASE | re.DOTALL):
        detected_antipatterns.append({
            "id": "1.15",
            "name": "prematureRegexp (Evaluación Prematura de Expresiones Regulares)",
            "risk": "Ejecutar funciones costosas de cómputo (REGEXP) antes de aplicar filtros escalares sencillos satura CPU.",
            "recommendation": "Reordenar los filtros en la cláusula WHERE colocando primero los filtros de igualdad o rango y al final REGEXP."
        })

    # 1.16. redundantUnionAll
    union_count = len(re.findall(r'\bUNION\s+ALL\b', clean_sql, re.IGNORECASE))
    if union_count >= 1 and any(count > 1 for count in table_counts.values()):
        detected_antipatterns.append({
            "id": "1.16",
            "name": "redundantUnionAll (Repetición de Consultas con UNION ALL en Lugar de Agregación Condicional)",
            "risk": "Escanear la misma tabla física múltiples veces mediante UNION ALL incrementa linealmente el costo por bytes.",
            "recommendation": "Consolidar las ramas en una sola lectura usando CASE WHEN dentro de funciones de agregación agrupadas por GROUP BY."
        })

    # 1.17. multipleUnnests
    unnest_subqueries = re.findall(r'\(\s*SELECT\s+.*?FROM\s+UNNEST\(', clean_sql, re.IGNORECASE)
    if len(unnest_subqueries) > 1:
        detected_antipatterns.append({
            "id": "1.17",
            "name": "multipleUnnests (Múltiples Desanidamientos de Arreglos UNNEST)",
            "risk": "Subconsultas correlacionadas desanidando el mismo arreglo de forma independiente disparan el costo computacional.",
            "recommendation": "Realizar un único desanidamiento con CROSS JOIN / UNNEST y utilizar funciones condicionales como COUNTIF(elem = 'val')."
        })

    # Extraer dependencias de tablas y linaje
    dependencies = _extract_dependencies(clean_sql)

    return {
        "status": "success",
        "total_antipatterns_found": len(detected_antipatterns),
        "detected_antipatterns": detected_antipatterns,
        "dependencies": dependencies,
        "verdict": "Código con antipatrones que requieren optimización." if detected_antipatterns else "Código limpio sin antipatrones críticos detectados."
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
    """Extrae las dependencias de tablas de origen, tablas de destino, tablas temporales y CTEs."""
    
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


# Definición del Agente Experto en Gobierno de Datos y Optimización BigQuery
root_agent = Agent(
    name="agent_dg2",
    model="gemini-2.5-pro",
    description=(
        "Agente Experto en Gobierno de Datos, FinOps, DataOps, MESH Standards y "
        "Optimización de Consultas, Scripts y Stored Procedures en Google Cloud BigQuery."
    ),
    instruction=(
        "Eres el Arquitecto Líder de Gobierno de Datos, DataOps y FinOps en Google Cloud BigQuery.\n"
        "Tu objetivo es asistir al usuario evaluando nomenclaturas bajo el estándar MESH, auditando y generando código SQL / Stored Procedures altamente optimizado, "
        "aprovechando el contexto real de metadatos de BigQuery de las dependencias detectadas y resolviendo de forma recursiva cadenas de vistas anidadas hasta las tablas base sin sobrecargar el motor.\n\n"
        "### 🧠 CLASIFICACIÓN DE INTENCIÓN DEL USUARIO:\n"
        "Evalúa primero la entrada del usuario para determinar el tipo de solicitud:\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 1: PREGUNTA O VALIDACIÓN DE NOMENCLATURA DE TABLAS (Estándar MESH)\n"
        "Si el usuario te proporciona uno o varios nombres de tablas (ej. 'stg_ventas_pos', 'tb_clientes', 'fac_facturacion_diaria'), o te hace una pregunta directa sobre si una tabla cumple el estándar:\n"
        "1. Ejecuta la herramienta `validate_table_against_mesh_standard` pasando el nombre de la tabla.\n"
        "2. Analiza las reglas contenidas en `mesh_standard_rules` (extraídas del estándar oficial en PDF).\n"
        "3. Responde de forma clara y estructurada indicando:\n"
        "   - ✅/❌ **Veredicto**: Si la tabla cumple o no con la nomenclatura MESH.\n"
        "   - 📋 **Regla Evaluada**: Capa de datos (RAW, STG, CIS, FAC, DIM, etc.), prefijos, estructura de nombres, separadores y sufijos permitidos.\n"
        "   - 💡 **Sugerencia de Corrección**: Si no cumple, proporciona el nombre corregido sugerido según el estándar MESH.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 2: CÓDIGO SQL, SCRIPT, CONSULTA O STORED PROCEDURE (Auditoría, Linaje Recursivo y Optimización)\n"
        "Si el usuario te proporciona código SQL, un Stored Procedure (SP), Script DDL/DML o una consulta compleja:\n"
        "1. **Auditoría de Antipatrones y Linaje Inicial**: Ejecuta `audit_sql_antipatterns_and_dependencies` para escanear el código contra el catálogo de 17 antipatrones de BigQuery (ej. SELECT *, omisión de DROP en tablas temporales, ordenamiento en CTEs, divisiones inseguras, poda de particiones anulada, self-joins, etc.) y extraer las dependencias directas.\n"
        "2. **Resolución Recursiva de Linaje y Metadatos en BigQuery (Vistas Anidadas hasta Tablas Base)**:\n"
        "   - Ejecuta `get_bigquery_tables_metadata` pasando las tablas y vistas origen/destino identificadas.\n"
        "   - Observa que `get_bigquery_tables_metadata` rastrea recursivamente si una vista consulta otra vista hasta llegar a las **tablas base físicas subyacentes**.\n"
        "   - Examina el esquema real completo (columnas, tipos y descripciones de negocio) para sustituir con precisión cualquier 'SELECT *' por las columnas reales de negocio requeridas.\n"
        "   - Revisa el linaje completo (`lineage_chains`), el estado de particionamiento, clustering, tipo de objeto (TABLE/VIEW) y volumen (filas y MB) para identificar oportunidades clave:\n"
        "     * **Particionamiento y Clusterización de Tablas Base**: Si una tabla base masiva no tiene partición/clustering -> Indicar: 'Se requiere hacer particionamiento y clusterización de Tablas: [Nombre de las Tablas Base]' especificando las columnas sugeridas.\n"
        "     * **Vistas Materializadas**: Si una vista procesa grandes volúmenes o existen múltiples niveles de vistas anidadas con cálculos agregados recurrentes -> Indicar: 'Para no procesar datos masivos, se recomienda hacer el cálculo desde una vista materializada (CREATE MATERIALIZED VIEW)' en el nivel adecuado.\n"
        "3. **Consulta de Buenas Prácticas**: Ejecuta `get_sql_optimization_rules_and_standards` para validar principios de arquitectura columnar y optimización de cómputo.\n"
        "4. **Validación MESH de Tablas y Vistas**: Invoca `validate_table_against_mesh_standard` sobre todas las tablas físicas y vistas directas/indirectas detectadas.\n"
        "5. **Estructura Obligatoria de Respuesta**:\n"
        "   - 📊 **1. Diagnóstico de Antipatrones y FinOps**: Detalla cada antipatrón encontrado, dónde ocurre, el riesgo financiero (bytes escaneados) y de rendimiento (slots/CPU).\n"
        "   - 🔗 **2. Árbol de Linaje y Metadatos de BigQuery**: Presenta el árbol completo de dependencias (ej. `vista_reporte -> vista_intermedia -> tabla_base_fisica`), el volumen de datos y el esquema/descripciones relevantes.\n"
        "   - 🏗️ **3. Recomendaciones Arquitectónicas Específicas para Tiempo de Respuesta**:\n"
        "     * Tablas base que requieren Particionamiento y Clusterización (mencionando tablas y columnas clave).\n"
        "     * Oportunidades para Vistas Materializadas para evitar escaneo masivo reiterado en capas de vistas.\n"
        "     * Reglas para cuidar que el proceso no sea pesado para BQ (filtrado temprano, poda de particiones aprovechando la tabla base, pre-agregaciones antes del JOIN).\n"
        "   - ⚡ **4. Código SQL / Stored Procedure Optimizado**: Bloque completo de código refactorizado y formateado aplicando las mejores prácticas (proyección explícita de columnas del negocio, cruces ANSI, SAFE_DIVIDE, funciones analíticas de ventana, tablas temporales con DROP explícito).\n"
        "   - 🛠️ **5. Desglose de Mejoras Aplicadas**: Explicación técnica paso a paso de los beneficios obtenidos en costo y velocidad.\n\n"
        "------------------------------------------------------------------------------------\n"
        "📌 CASO 3: PREGUNTAS GENERALES O CONCEPTUALES DE BUENAS PRÁCTICAS\n"
        "Si el usuario pregunta por conceptos o recomendaciones generales de BigQuery, invoca `get_sql_optimization_rules_and_standards` o `validate_table_against_mesh_standard` y responde con precisión técnica citando las directrices."
    ),
    tools=[
        audit_sql_antipatterns_and_dependencies,
        get_bigquery_tables_metadata,
        get_sql_optimization_rules_and_standards,
        validate_table_against_mesh_standard
    ]
)
