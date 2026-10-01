# GUÍA UNIFICADA: ANTIPATRONES SQL Y BUENAS PRÁCTICAS EN BIGQUERY

Esta guía documenta los antipatrones oficiales de SQL en Google Cloud BigQuery organizados por pilares de impacto técnico y financiero (FinOps / DataOps), así como sus soluciones recomendadas.

---

## PILAR 1: I/O, Particiones, Clúster y Escaneo de Columnas (Facturación y FinOps)

### 1.1 `selectStar` (Uso Indiscriminado de SELECT *)
* **Riesgo:** BigQuery factura por bytes leídos. `SELECT *` lee todas las columnas físicas de la tabla columnar, multiplicando costos y saturando memoria.
* **Solución:** Proyectar explícitamente solo las columnas requeridas (`SELECT col1, col2`).

### 1.12 `partitionPruningDisabled` (Deshabilitación de Poda de Particiones por Funciones)
* **Riesgo:** Usar funciones sobre columnas de partición (ej. `DATE(timestamp_col) = '2026-06-13'` o `CAST(id AS STRING) = ...`) anula el índice de partición y fuerza un Full Table Scan.
* **Solución:** Filtrar directamente sobre el campo de partición: `timestamp_col >= '2026-06-13 00:00:00' AND timestamp_col < '2026-06-14 00:00:00'`.

### 1.18 `unpartitionedMergeTarget` (Escaneo Completo en MERGE Destino)
* **Riesgo:** Sentencias `MERGE INTO target USING source ON target.id = source.id` sin incluir la columna de partición de la tabla destino en la cláusula `ON` provocan escaneo histórico total en cada ejecución batch/ETL.
* **Solución:** Incluir obligatoriamente la columna de partición de la tabla destino en la condición `ON`: `AND target.fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)`.

### 1.19 `lateFiltering` (Filtros Tardíos / Falta de Predicate Pushdown)
* **Riesgo:** Subconsultas o CTEs que leen tablas masivas sin filtrar en la consulta inicial, aplicando el `WHERE` únicamente en la capa exterior.
* **Solución:** Inyectar los filtros inmediatamente en la primera CTE o subconsulta donde se lee la tabla.

### 1.8 `orderByWithoutLimit` (Ordenamiento Masivo en CTEs Intermedias)
* **Riesgo:** Ordenar datos dentro de subconsultas o CTEs intermedias sin `LIMIT` desperdicia CPU y memoria en ordenamientos inútiles.
* **Solución:** Eliminar `ORDER BY` en subconsultas intermedias; ordenar únicamente en la consulta final cuando sea estrictamente necesario.

---

## PILAR 2: Slots, Memoria y Tráfico de Red / Shuffle (Spill y Rendimiento)

### 1.5 `joinOrder` (Cruces Implícitos no ANSI y Orden Invertido de JOINs)
* **Riesgo:** Cruces no ANSI (`FROM t1, t2 WHERE t1.id = t2.id`) o colocar la tabla pequeña en el `FROM` y la masiva en el `JOIN` impide la distribución en memoria (Broadcast Hash Join) y provoca Shuffle Spill.
* **Solución:** Colocar la tabla de mayor volumen a la izquierda (`FROM tabla_masiva`) y las tablas pequeñas/catálogos a la derecha (`JOIN tabla_pequena ON ...`).

### 1.14 `selfJoin` (Uso de Self-JOINs en Lugar de Funciones de Ventana)
* **Riesgo:** Unir una tabla consigo misma para comparar filas consecutivas duplica los bytes leídos y satura el shuffle.
* **Solución:** Usar funciones de ventana analíticas: `LAG()`, `LEAD()`, `FIRST_VALUE()`.

### 1.20 `joinWithoutPreReduction` (Falta de Reducción Previa al JOIN)
* **Riesgo:** Cruzar tablas transaccionales crudas con millones de filas antes de agrupar o sumarizar, multiplicando el tráfico de red interno.
* **Solución:** Pre-agrupar y sumarizar tablas transaccionales en CTEs antes de cruzarlas con tablas descriptivas.

### 1.13 `skewedJoinKeys` (Cruces sobre Claves Desbalanceadas o Nulas)
* **Riesgo:** Unir tablas sobre claves con alta concentración de nulos o comodines (`'99999'`, `NULL`, `'-1'`) sobrecarga un solo slot de cómputo (data skew).
* **Solución:** Filtrar o aislar valores nulos y comodines antes del cruce (`WHERE clave IS NOT NULL AND clave != '99999'`).

### 1.21 `castInJoinOn` (Conversión de Tipos al Vuelo en Cláusula ON)
* **Riesgo:** Cláusulas `ON` que realizan conversiones (ej. `ON CAST(a.id AS STRING) = b.id_str`) impiden la indexación interna de hash joins.
* **Solución:** Proyectar la columna casteada en la CTE inicial y unir sobre tipos de datos ya homologados.

### 1.22 `massiveCountDistinct` (COUNT DISTINCT en Volúmenes Masivos)
* **Riesgo:** Uso de `COUNT(DISTINCT)` sobre campos de alta cardinalidad en petabytes de datos satura la memoria de los slots.
* **Solución:** Evaluar `APPROX_COUNT_DISTINCT(campo)` para escenarios donde un margen de error < 1% sea aceptable.

### 1.23 `doubleDeduplication` (Doble Deduplicación Innecesaria)
* **Riesgo:** Uso concurrente de `SELECT DISTINCT` y `GROUP BY` sobre las mismas columnas añade una fase de ordenamiento redundante.
* **Solución:** Eliminar `DISTINCT` y conservar únicamente `GROUP BY`.

---

## PILAR 3: Eficiencia Analítica, Ventanas y Deduplicación

### 1.6 `latestRecord` (Obtención Ineficiente del Último Registro con ORDER BY ... LIMIT 1)
* **Riesgo:** `ORDER BY col DESC LIMIT 1` fuerza un ordenamiento global en un único slot distribuidor.
* **Solución:** Usar funciones de ventana: `QUALIFY ROW_NUMBER() OVER(PARTITION BY entidad_id ORDER BY fecha DESC) = 1`.

### 1.24 `windowReshuffleOverhead` (Sobrecarga por Re-shuffling de Ventanas)
* **Riesgo:** Múltiples funciones analíticas `OVER(...)` con particiones u ordenamientos dispares que fuerzan múltiples redistribuciones de datos en los slots.
* **Solución:** Unificar especificaciones de ventana idénticas utilizando la cláusula `WINDOW w AS (PARTITION BY ... ORDER BY ...)`.

### 1.16 `redundantUnionAll` (Repetición de Consultas con UNION ALL)
* **Riesgo:** Repetir lecturas de la misma tabla física en múltiples ramas de `UNION ALL` multiplica linealmente el costo por escaneo.
* **Solución:** Consolidar en una sola pasada usando `CASE WHEN` y agregaciones condicionales (`SUM(CASE WHEN ...)` o `COUNTIF(...)`) agrupadas por `GROUP BY`.

---

## PILAR 4: Rendimiento en Cadenas, JSON, Arreglos y Aritmética

### 1.15 `prematureRegexp` (Evaluación Prematura de Expresiones Regulares)
* **Riesgo:** Usar `REGEXP_CONTAINS` para búsquedas simples de prefijo, sufijo o subcadena, o evaluar expresiones regulares antes de filtros exactos, satura la CPU.
* **Solución:** Usar `STARTS_WITH()`, `ENDS_WITH()`, `CONTAINS_SUBSTR()` o `LIKE`, y ordenar el `WHERE` evaluando primero los filtros escalares.

### 1.17 `multipleUnnests` (Múltiples Desanidamientos de Arreglos UNNEST)
* **Riesgo:** Subconsultas correlacionadas desanidando el mismo array repetidamente disparan el costo computacional.
* **Solución:** Realizar un único `CROSS JOIN UNNEST(array)` y utilizar agregaciones condicionales (`COUNTIF(...)`).

### 1.25 `repetitiveJsonExtraction` (Parseo Repetitivo de JSON)
* **Riesgo:** Invocación repetida de `JSON_EXTRACT_SCALAR` fila por fila en múltiples cláusulas.
* **Solución:** Usar navegación nativa (`col.campo.subcampo`) o extraer campos una sola vez en la CTE inicial.

### 1.9 `stringComparison` (Comparación de Cadenas sin Normalización)
* **Riesgo:** Inconsistencias lógicas y fallas en filtros por diferencias de mayúsculas/minúsculas o espacios.
* **Solución:** Normalizar explícitamente: `LOWER(TRIM(columna)) = LOWER(TRIM('valor'))`.

### 1.11 `whereOrder` (División Insegura / Orden de Evaluación en WHERE)
* **Riesgo:** BigQuery evalúa predicados en paralelo sin orden secuencial garantizado, lo que causa errores por división entre cero en tiempo de ejecución.
* **Solución:** Usar siempre `SAFE_DIVIDE(a, b)` o `a / NULLIF(b, 0)`.

### 1.26 `timeFunctionMemoization` (Reevaluación de Funciones de Tiempo No Deterministas)
* **Riesgo:** Invocaciones repetidas de `CURRENT_DATETIME()` o `CURRENT_DATE()` en la misma consulta o script generan discrepancias y cálculos redundantes.
* **Solución:** Memoizar el valor asignándolo a una variable al inicio del script (`DECLARE v_hoy DATE DEFAULT CURRENT_DATE();`).

---

## PILAR 5: Procedimientos Almacenados (SPs), Scripts y Control Transaccional

### 1.27 `iterativeRowByRow` (Bucles Iterativos Fila por Fila)
* **Riesgo:** Usar bucles (`WHILE`, `LOOP`, `FOR`) o cursores dentro de SPs para procesar registros fila a fila anula el paralelismo MPP y degrada drásticamente el rendimiento.
* **Solución:** Vectorizar la lógica mediante operaciones DML masivas (`MERGE`, `ARRAY_AGG` + `UNNEST`).

### 1.7 `multipleCTES` (Exceso de CTEs Fragmentadas o Re-ejecutadas)
* **Riesgo:** Si una CTE pesada se referencia 2 o más veces en la misma consulta, BigQuery la recalcula en cada invocación.
* **Solución:** Materializarla en `CREATE OR REPLACE TEMP TABLE tmp_nombre AS ...`.

### 1.3 `droppedPersistentTable` (Uso de Tablas Físicas como Temporales)
* **Riesgo:** Crear y borrar repetidamente tablas físicas persistentes en procesos batch satura operaciones DDL de metadatos de GCP.
* **Solución:** Usar `CREATE OR REPLACE TEMP TABLE` o trabajar con operaciones DML (`INSERT`, `MERGE`) en tablas persistentes predefinidas.

### 1.2 `missingDropStatement` (Omisión de DROP TABLE en Tablas Temporales)
* **Riesgo:** Tablas temporales creadas en scripts o Stored Procedures que no se liberan consumen espacio de sesión y saturan metadatos.
* **Solución:** Agregar siempre `DROP TABLE IF EXISTS <tabla_temp>;` al terminar el bloque de procesamiento.

### 1.4 `dynamicPredicate` (Construcción Dinámica de Filtros por Concatenación)
* **Riesgo:** Concatenar strings en `EXECUTE IMMEDIATE` genera vulnerabilidades de Inyección SQL y desactiva el optimizador de consultas.
* **Solución:** Usar consultas estáticas parametrizadas o la cláusula `USING` con tipos de datos estrictos.

### 1.28 `unhandledExceptionLogging` (Omisión de Captura de Error en Excepciones)
* **Riesgo:** Bloques `EXCEPTION WHEN ERROR THEN` que solo asignan variables de estado sin capturar `@@error.message` ni metadatos del error.
* **Solución:** Encapsular bloques procedimentales capturando `SET v_error = @@error.message;`.

---

## PILAR 6: UDFs (User-Defined Functions)

### 1.29 `javascriptUDFs` (UDFs en JavaScript Innecesarias)
* **Riesgo:** Las UDFs en JavaScript (`LANGUAGE js`) no se pueden optimizar en el motor vectorizado ni paralelizar eficientemente en slots.
* **Solución:** Reescribir la lógica en SQL nativo (`LANGUAGE sql`).

### 1.30 `nonDeterministicUDFs` (Falta de Cláusula DETERMINISTIC)
* **Riesgo:** UDFs de cálculo puro no marcadas como deterministas impiden la optimización y reutilización de cómputo.
* **Solución:** Incluir la cláusula `DETERMINISTIC` en UDFs de cálculo puro.

---

## PILAR 7: Almacenamiento y FinOps en BigQuery

1. **Particionamiento:** Particionar tablas masivas (>100k filas) por día/mes para acotar el volumen escaneado.
2. **Clusterización:** Clusterizar por las 1 a 4 columnas más utilizadas en filtros de igualdad y llaves de JOIN.
3. **Vistas Materializadas:** Cuando se ejecutan cálculos agregados recurrentes sobre tablas base pesadas, crear una Vista Materializada (`CREATE MATERIALIZED VIEW`) para precalcular resultados y no saturar slots.