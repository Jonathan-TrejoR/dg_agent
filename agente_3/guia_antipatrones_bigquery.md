# GUÍA UNIFICADA: ANTIPATRONES SQL Y BUENAS PRÁCTICAS EN BIGQUERY

Esta guía documenta los antipatrones oficiales de SQL en Google Cloud BigQuery organizados por pilares de impacto técnico y financiero (FinOps / DataOps), así como sus soluciones recomendadas.

---

## PILAR 1: I/O, Particiones, Clúster y Escaneo de Columnas (Facturación y FinOps)

### 1.1 `selectStar` (Uso Indiscriminado de SELECT * y SELECT * EXCEPT)
* **Riesgo:** BigQuery factura por bytes leídos. `SELECT *` (o usar `SELECT * EXCEPT(...)` en tablas anchas con decenas de columnas) lee todas las columnas físicas de la tabla columnar, multiplicando costos, saturando memoria y acoplando el código a cambios de esquema.
* **Solución:** Proyectar explícitamente solo las columnas requeridas (`SELECT col1, col2`). Reservar `* EXCEPT` únicamente sobre CTEs previas que ya hayan acotado las columnas estrictamente necesarias.

### 1.12 `partitionPruningDisabled` (Deshabilitación de Poda de Particiones por Funciones)
* **Riesgo:** Usar funciones, conversiones o aritmética sobre columnas de partición (ej. `DATE(timestamp_col) = '2026-06-13'`, `EXTRACT(YEAR FROM fecha) = 2026`, `COALESCE(fecha, ...)`, `CAST(id AS STRING) = ...`) anula la poda estática de particiones (SARGability) y fuerza un Full Table Scan.
* **Solución:** Filtrar directamente sobre el campo de partición sin transformarlo: `timestamp_col >= '2026-06-13 00:00:00' AND timestamp_col < '2026-06-14 00:00:00'`.

### 1.18 `unpartitionedMergeTarget` (Escaneo Completo en MERGE Destino)
* **Riesgo:** Sentencias `MERGE INTO target USING source ON target.id = source.id` sin incluir la columna de partición de la tabla destino en la cláusula `ON` provocan escaneo histórico total en cada ejecución batch/ETL.
* **Solución:** Incluir obligatoriamente un predicado constante de partición de la tabla destino en la condición `ON`: `AND target.fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)`.

### 1.19 `lateFiltering` (Filtros Tardíos / Falta de Predicate Pushdown)
* **Riesgo:** Subconsultas o CTEs que leen tablas masivas sin filtrar en la consulta inicial, aplicando el `WHERE` únicamente en la capa exterior tras haber ejecutado `JOINs`, funciones de ventana o agregaciones.
* **Solución:** Inyectar los filtros (`WHERE` de partición, clúster y negocio) inmediatamente en la primera CTE o subconsulta donde se lee la tabla física.

### 1.8 `orderByWithoutLimit` (Ordenamiento Masivo en CTEs Intermedias)
* **Riesgo:** Ordenar datos dentro de subconsultas, vistas o CTEs intermedias sin `LIMIT` desperdicia CPU y memoria en ordenamientos globales inútiles que el motor distribuido no garantiza preservar en capas posteriores.
* **Solución:** Eliminar `ORDER BY` en subconsultas intermedias; ordenar únicamente en la consulta final de presentación cuando sea estrictamente necesario.

### 1.31 `missingPartitionFilter` (Omisión Total de Filtro de Partición en Tabla Particionada)
* **Riesgo:** Consultar una tabla particionada (por tiempo, `_PARTITIONTIME` o rango entero) filtrando únicamente por columnas de negocio o de clúster sin incluir la columna de partición en el `WHERE` escanea la historia completa de la tabla.
* **Solución:** Incluir siempre el filtro sobre la columna de partición en el `WHERE` y activar `OPTIONS(require_partition_filter = TRUE)` en el DDL de tablas masivas.

### 1.32 `dynamicPartitionPruningFailure` (Fallo de Poda de Particiones por Subconsultas o JOINs Dinámicos)
* **Riesgo:** Filtrar la columna de partición usando una subconsulta dinámica (`WHERE fecha IN (SELECT MAX(fecha) FROM otra_tabla)`) o mediante la condición `ON` de un `JOIN` impide que el optimizador conozca las particiones en tiempo de compilación, escaneando toda la tabla.
* **Solución:** Precalcular el límite en una variable escalar antes de la consulta (`DECLARE v_max_fecha DATE DEFAULT (SELECT MAX(fecha) FROM ...);`) y usar la variable estática en el `WHERE fecha = v_max_fecha`.

### 1.33 `clusterPruningBypassed` (Inutilización del Orden Jerárquico de Clusterización)
* **Riesgo:** Filtrar únicamente por la segunda, tercera o cuarta columna definida en `CLUSTER BY (col1, col2, col3)` omitiendo `col1`, o aplicar funciones sobre las columnas clusterizadas, reduce drásticamente la poda de bloques (*block pruning*).
* **Solución:** Construir los predicados del `WHERE` respetando el orden de prefijo de las columnas de clusterización y sin envolverlas en funciones.

### 1.34 `wildcardTableUnboundedScan` (Escaneo Abierto en Tablas Comodín sin `_TABLE_SUFFIX` Constante)
* **Riesgo:** Consultar tablas fragmentadas con comodín (`FROM \`proyecto.dataset.tabla_*\``) sin filtrar `_TABLE_SUFFIX`, o aplicando funciones/subconsultas sobre `_TABLE_SUFFIX`, escanea todas las tablas históricas que coincidan con el prefijo.
* **Solución:** Filtrar inmediatamente con rangos literales sobre `_TABLE_SUFFIX` (`WHERE _TABLE_SUFFIX BETWEEN '20260101' AND '20260131'`) y planificar la migración hacia una única tabla particionada.

### 1.35 `limitFalseEconomy` (Falsa Economía de Costos con `LIMIT` sin Poda Previa)
* **Riesgo:** Confiar en `LIMIT N` al final de la consulta para reducir costos cuando existen operadores bloqueantes previos (`ORDER BY`, `GROUP BY`, `DISTINCT`, `JOIN`, ventanas) o sin filtro de partición, provocando igualmente el cobro del escaneo total.
* **Solución:** Restringir siempre por partición y clúster en el `WHERE`, o utilizar `TABLESAMPLE SYSTEM (1 PERCENT)` para muestreo exploratorio con reducción real de I/O.

---

## PILAR 2: Slots, Memoria y Tráfico de Red / Shuffle (Spill y Rendimiento)

### 1.5 `joinOrder` (Cruces Implícitos no ANSI y Orden Invertido de JOINs)
* **Riesgo:** Cruces no ANSI (`FROM t1, t2 WHERE t1.id = t2.id`) o colocar la tabla pequeña en el `FROM` y la masiva en el `JOIN` impide la distribución óptima en memoria (Broadcast Hash Join) y provoca Shuffle Spill.
* **Solución:** Usar sintaxis ANSI explícita y colocar la tabla de mayor volumen a la izquierda (`FROM tabla_masiva`) y las tablas pequeñas/catálogos a la derecha (`JOIN tabla_pequena ON ...`).

### 1.14 `selfJoin` (Uso de Self-JOINs en Lugar de Funciones de Ventana)
* **Riesgo:** Unir una tabla consigo misma para comparar filas consecutivas, calcular diferencias temporales o hallar acumulados duplica los bytes leídos y satura el shuffle.
* **Solución:** Usar funciones de ventana analíticas: `LAG()`, `LEAD()`, `FIRST_VALUE()`, `SUM() OVER(...)`.

### 1.20 `joinWithoutPreReduction` (Falta de Reducción Previa al JOIN)
* **Riesgo:** Cruzar tablas transaccionales crudas con millones de filas antes de agrupar, filtrar o deduplicar, multiplicando el tráfico de red interno (Shuffle).
* **Solución:** Pre-filtrar, deduplicar o pre-agrupar las tablas transaccionales en CTEs antes de cruzarlas con otras tablas.

### 1.13 `skewedJoinKeys` (Cruces sobre Claves Desbalanceadas o Nulas)
* **Riesgo:** Unir tablas sobre claves con alta concentración de nulos o comodines (`'99999'`, `NULL`, `'-1'`, `'N/A'`, `''`) sobrecarga un solo slot de cómputo (*data skew* / *long tail*).
* **Solución:** Filtrar o aislar valores nulos y comodines antes del cruce (`WHERE clave IS NOT NULL AND clave NOT IN ('99999', '-1', '')`), o reemplazar valores por defecto por un identificador único aleatorio cuando deban conservarse en un `LEFT JOIN`.

### 1.21 `castInJoinOn` (Conversión de Tipos o Expresiones al Vuelo en Cláusula ON)
* **Riesgo:** Cláusulas `ON` que realizan conversiones o funciones (ej. `ON CAST(a.id AS STRING) = TRIM(b.id_str)`) impiden la indexación directa de los Hash Joins y reevalúan la función por cada combinación.
* **Solución:** Proyectar la columna ya casteada y limpia en la CTE inicial y unir sobre tipos de datos previamente homologados.

### 1.22 `massiveCountDistinct` (COUNT DISTINCT en Volúmenes Masivos)
* **Riesgo:** Uso de `COUNT(DISTINCT)` exacto sobre campos de alta cardinalidad en grandes volúmenes de datos satura la memoria de los slots y el Shuffle.
* **Solución:** Evaluar `APPROX_COUNT_DISTINCT(campo)` o sketches `HLL_COUNT.INIT` / `HLL_COUNT.MERGE` para escenarios analíticos donde una precisión > 99% sea aceptable.

### 1.23 `doubleDeduplication` (Doble Deduplicación Innecesaria)
* **Riesgo:** Uso concurrente de `SELECT DISTINCT` y `GROUP BY` sobre las mismas columnas añade una fase de verificación/ordenamiento redundante.
* **Solución:** Eliminar `DISTINCT` y conservar únicamente `GROUP BY`.

### 1.10 `uncorrelatedNotIn` (Antijoin Peligroso e Ineficiente con `NOT IN (SELECT ...)`)
* **Riesgo:** Usar `WHERE col NOT IN (SELECT col FROM tabla_b)` descarta silenciosamente el 100% de los resultados si la subconsulta contiene un solo valor `NULL`, y además degrada el plan de ejecución a comparaciones cuadráticas en listas grandes.
* **Solución:** Reemplazar `NOT IN (SELECT ...)` por `WHERE NOT EXISTS (SELECT 1 FROM tabla_b b WHERE b.col = a.col)` o `LEFT JOIN tabla_b b ON a.col = b.col WHERE b.col IS NULL`.

### 1.36 `nonEquiJoin` (Cruces por Desigualdad o Rangos sin Llave de Igualdad en `ON`)
* **Riesgo:** Unir tablas usando únicamente operadores de desigualdad (`<`, `>`, `!=`, `BETWEEN`, `LIKE`) en la cláusula `ON` impide el uso de Hash Join y fuerza un Nested Loop Join (producto cartesiano filtrado), agotando los slots (`Resources exceeded`).
* **Solución:** Incluir obligatoriamente al menos una condición de igualdad (`a.entidad_id = b.entidad_id`) en la cláusula `ON` junto con las condiciones de rango.

### 1.37 `orInJoinCondition` (Disyunción `OR` dentro de la Cláusula `ON` del JOIN)
* **Riesgo:** Condiciones como `ON a.id = b.id OR a.codigo = b.codigo` desactivan la optimización por Hash Join e inducen un producto cartesiano evaluado fila por fila.
* **Solución:** Dividir en dos `LEFT JOIN` independientes por cada llave (consolidando con `COALESCE`) o separar en dos consultas con `UNION ALL`.

### 1.38 `accidentalManyToManyJoin` (Explosión Combinatoria por JOIN N:M o `CROSS JOIN` Masivo)
* **Riesgo:** Cruzar dos tablas donde ninguna tiene unicidad garantizada en la llave de cruce (relación Muchos-a-Muchos no intencional) o aplicar `CROSS JOIN` entre tablas grandes multiplica exponencialmente las filas y provoca *Shuffle Spill to Disk*.
* **Solución:** Garantizar unicidad en el catálogo/dimensión antes del cruce (`QUALIFY ROW_NUMBER() ... = 1` o `GROUP BY`) y limitar `CROSS JOIN` a tablas de parámetros de muy baja cardinalidad.

### 1.39 `highCardinalityGroupBy` (Inclusión de Atributos Descriptivos Pesados en `GROUP BY`)
* **Riesgo:** Agrupar por decenas de columnas descriptivas o strings largos (`GROUP BY id, nombre, direccion, descripcion, ...`) cuando dependen funcionalmente del `id` multiplica los bytes serializados en el Shuffle.
* **Solución:** Agrupar únicamente por la llave primaria (`GROUP BY id`) y envolver los atributos descriptivos dependientes en `ANY_VALUE(nombre)` o unirlos después de agrupar.

---

## PILAR 3: Eficiencia Analítica, Ventanas y Deduplicación

### 1.6 `latestRecord` (Obtención Ineficiente del Último Registro con ORDER BY ... LIMIT 1)
* **Riesgo:** `ORDER BY col DESC LIMIT 1` para obtener el registro más reciente fuerza un ordenamiento global en un único slot distribuidor, o requiere subconsultas correlacionadas costosas.
* **Solución:** Usar funciones de ventana con filtrado nativo: `QUALIFY ROW_NUMBER() OVER(PARTITION BY entidad_id ORDER BY fecha DESC) = 1`, o agregaciones nativas `MAX_BY(STRUCT(...), fecha)` / `ARRAY_AGG( t ORDER BY fecha DESC LIMIT 1 )[OFFSET(0)]`.

### 1.24 `windowReshuffleOverhead` (Sobrecarga por Re-shuffling de Ventanas)
* **Riesgo:** Múltiples funciones analíticas `OVER(...)` con particiones u ordenamientos dispares (o repetidos textualmente) que fuerzan múltiples redistribuciones y ordenamientos de datos en los slots.
* **Solución:** Unificar especificaciones de ventana compartidas utilizando la cláusula `WINDOW w AS (PARTITION BY ... ORDER BY ...)` y alinear las claves de partición cuando sea posible.

### 1.16 `redundantUnionAll` (Repetición de Consultas con UNION ALL sobre la Misma Tabla)
* **Riesgo:** Repetir lecturas de la misma tabla física en múltiples ramas de `UNION ALL` (cambiando solo el filtro `WHERE` o la métrica calculada) multiplica linealmente el costo por escaneo.
* **Solución:** Consolidar en una sola lectura de la tabla usando `CASE WHEN`, `COUNTIF(...)`, `SUM(IF(...))` o desanidando un arreglo de métricas con `UNNEST([...])`.

### 1.40 `unpartitionedWindowFunction` (Funciones de Ventana Globales sin `PARTITION BY`)
* **Riesgo:** Ejecutar `ROW_NUMBER() OVER(ORDER BY fecha)` o `SUM(x) OVER(ORDER BY fecha)` sin cláusula `PARTITION BY` concentra el 100% de las filas de la consulta en un único worker/slot para ordenamiento secuencial, causando fallos por `Resources exceeded during query execution`.
* **Solución:** Incluir siempre una clave de partición con buena distribución (`PARTITION BY entidad_id`) o sustituir rankings globales por `APPROX_QUANTILES`.

### 1.41 `subqueryFilterOnWindow` (Subconsulta Envolvente para Filtrar Ventanas en Lugar de `QUALIFY`)
* **Riesgo:** Crear una CTE o subconsulta extra solo para filtrar el resultado de una función de ventana (`SELECT * FROM (SELECT *, ROW_NUMBER() OVER(...) AS rn FROM t) WHERE rn = 1`) materializa columnas auxiliares innecesarias y añade verbosidad al plan.
* **Solución:** Filtrar directamente en el mismo nivel de consulta utilizando `QUALIFY ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ...) = 1`.

### 1.42 `unboundedWindowFrame` (Marcos de Ventana Ineficientes con `LAST_VALUE` o `RANGE`)
* **Riesgo:** Usar `LAST_VALUE(col) OVER (PARTITION BY id ORDER BY fecha)` sin definir el marco aplica por defecto `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` (produciendo errores lógicos al devolver la fila actual), y el uso de `RANGE` sobre muchos valores empatados consume mucha más memoria que `ROWS`.
* **Solución:** Reemplazar `LAST_VALUE` por `FIRST_VALUE` invirtiendo el `ORDER BY fecha DESC`, o declarar explícitamente `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`.

### 1.43 `arrayAggWithoutLimit` (Acumulación Ilimitada en Memoria con `ARRAY_AGG` / `STRING_AGG`)
* **Riesgo:** Ejecutar `ARRAY_AGG(col ORDER BY fecha)` o `STRING_AGG(col)` sobre grupos con cientos de miles de registros puede superar el límite de tamaño de fila (100 MB) o agotar la memoria del slot.
* **Solución:** Restringir la acumulación agregando `LIMIT N` dentro de la función (`ARRAY_AGG(col ORDER BY fecha DESC LIMIT 100)`).

### 1.44 `exactQuantilesOnMassiveData` (Cálculo Exacto de Percentiles con `PERCENTILE_CONT` en Grandes Volúmenes)
* **Riesgo:** `PERCENTILE_CONT` y `PERCENTILE_DISC` son funciones analíticas que fuerzan la redistribución y el ordenamiento exacto en memoria de todas las filas de cada partición y no permiten `GROUP BY` directo.
* **Solución:** Utilizar la función agregada distribuida `APPROX_QUANTILES(columna, 100)[OFFSET(50)]` combinada con `GROUP BY`.

---

## PILAR 4: Rendimiento en Cadenas, JSON, Arreglos y Aritmética

### 1.15 `prematureRegexp` (Evaluación Prematura de Expresiones Regulares)
* **Riesgo:** Usar `REGEXP_CONTAINS`, `REGEXP_EXTRACT` o `REGEXP_REPLACE` para búsquedas simples de prefijo, sufijo o subcadena, o evaluar expresiones regulares antes de filtros exactos, satura la CPU.
* **Solución:** Usar funciones nativas de bajo costo (`STARTS_WITH()`, `ENDS_WITH()`, `CONTAINS_SUBSTR()`, `STRPOS()`, `LIKE`) y colocar los filtros escalares selectivos antes de cualquier regex.

### 1.17 `multipleUnnests` (Múltiples Desanidamientos de Arreglos UNNEST)
* **Riesgo:** Subconsultas correlacionadas desanidando el mismo array repetidamente, o múltiples `CROSS JOIN UNNEST` encadenados sobre arreglos independientes (generando producto cartesiano entre arreglos), disparan el costo computacional.
* **Solución:** Realizar un único desanidamiento o procesar el arreglo en una sola pasada local mediante `ARRAY(SELECT ... FROM UNNEST(arr))` y agregaciones condicionales (`COUNTIF(...)`).

### 1.25 `repetitiveJsonExtraction` (Parseo Repetitivo de JSON y Uso de JSON en STRING)
* **Riesgo:** Invocación repetida de `JSON_EXTRACT_SCALAR` / `JSON_VALUE` fila por fila sobre una columna `STRING` en múltiples cláusulas (`SELECT`, `WHERE`, `GROUP BY`).
* **Solución:** Almacenar el dato usando el tipo nativo `JSON` o `STRUCT` para aprovechar la lectura sub-columnar con notación de punto (`col.campo.subcampo` y `LAX_STRING()` / `LAX_INT64()`), o extraer los campos una sola vez en la CTE inicial.

### 1.9 `stringComparison` (Comparación de Cadenas sin Normalización)
* **Riesgo:** Inconsistencias lógicas y fallas en filtros o cruces por diferencias de mayúsculas/minúsculas, acentos o espacios laterales.
* **Solución:** Normalizar durante la ingesta/ETL o definir `COLLATE 'und:ci'` en las columnas de texto; si el dato crudo no está normalizado, aplicar `LOWER(TRIM(columna)) = 'valor_en_minusculas'` evitando recalcular funciones sobre el literal constante.

### 1.11 `whereOrder` (División Insegura / Orden de Evaluación en WHERE)
* **Riesgo:** BigQuery evalúa predicados en paralelo sin orden secuencial garantizado (`WHERE b != 0 AND a / b > 1` puede evaluar primero `a / b`), lo que causa errores fatales por división entre cero en tiempo de ejecución.
* **Solución:** Usar siempre `SAFE_DIVIDE(a, b)` o `a / NULLIF(b, 0)`.

### 1.26 `timeFunctionMemoization` (Reevaluación de Funciones de Tiempo No Deterministas)
* **Riesgo:** Invocaciones repetidas de `CURRENT_DATETIME()`, `CURRENT_TIMESTAMP()` o `CURRENT_DATE()` en múltiples sentencias de un script generan discrepancias temporales si la ejecución cruza la medianoche e impiden el uso de la caché de resultados.
* **Solución:** Memoizar el valor asignándolo a una variable al inicio del script (`DECLARE v_hoy DATE DEFAULT CURRENT_DATE('America/Mexico_City');`) especificando siempre la zona horaria explícita.

### 1.45 `unsafeTypeCast` (Conversiones de Tipo y Parseos Rígidos sin Prefijo `SAFE`)
* **Riesgo:** Usar `CAST(col AS INT64)`, `PARSE_DATE()`, `PARSE_DATETIME()` o `PARSE_JSON()` sobre datos crudos aborta todo el trabajo si una sola fila entre millones presenta un formato corrupto.
* **Solución:** Utilizar `SAFE_CAST(col AS INT64)` y el prefijo `SAFE.` en funciones escalares (`SAFE.PARSE_DATE(...)`, `SAFE.PARSE_JSON(...)`) para devolver `NULL` de forma controlada y auditar los rechazos sin detener el pipeline.

### 1.46 `correlatedScalarSubquery` (Subconsultas Escalares Correlacionadas en `SELECT` o `WHERE`)
* **Riesgo:** Escribir `(SELECT MAX(x) FROM tabla_b b WHERE b.id = a.id)` dentro del `SELECT` fuerza descorrelaciones internas costosas o falla en tiempo de ejecución (`Scalar subquery produced more than one element`) si la relación no es estrictamente 1:1.
* **Solución:** Pre-agrupar `tabla_b` por `id` en una CTE independiente y unirla mediante `LEFT JOIN`.

### 1.47 `leadingWildcardWithoutSearchIndex` (Búsquedas `LIKE '%texto%'` en Grandes Volúmenes sin Índice)
* **Riesgo:** Filtrar columnas de texto libre o logs masivos con comodín inicial (`LIKE '%error%'` o `REGEXP_CONTAINS`) obliga a inspeccionar cada byte de cada bloque leído.
* **Solución:** Crear un índice de búsqueda (`CREATE SEARCH INDEX`) sobre las columnas de texto/JSON y consultar mediante la función optimizada `SEARCH(columna, 'error')`.

---

## PILAR 5: Procedimientos Almacenados (SPs), Scripts y Control Transaccional

### 1.27 `iterativeRowByRow` (Bucles Iterativos Fila por Fila)
* **Riesgo:** Usar bucles (`WHILE`, `LOOP`, `FOR ... IN`) o cursores simulados dentro de SPs para ejecutar consultas o DMLs fila a fila anula la arquitectura MPP de BigQuery y multiplica la latencia de minutos a horas.
* **Solución:** Vectorizar la lógica en una sola operación basada en conjuntos (*set-based*) mediante `MERGE`, `INSERT ... SELECT` o `ARRAY_AGG` + `UNNEST`.

### 1.7 `multipleCTES` (Exceso de CTEs Fragmentadas o Re-ejecutadas)
* **Riesgo:** En BigQuery las CTEs (`WITH`) no se materializan automáticamente; si una CTE compleja se referencia 2 o más veces en la consulta, el motor suele recalcularla y re-escanear las tablas base en cada invocación.
* **Solución:** Materializar las transformaciones pesadas reutilizadas en múltiples pasos mediante `CREATE OR REPLACE TEMP TABLE tmp_nombre AS ...`.

### 1.3 `droppedPersistentTable` (Uso de Tablas Físicas como Temporales)
* **Riesgo:** Crear y borrar repetidamente tablas físicas persistentes (`CREATE TABLE ...; DROP TABLE ...;`) en procesos batch satura las cuotas de operaciones DDL de metadatos, ensucia el catálogo y genera costos de almacenamiento mínimo.
* **Solución:** Usar `CREATE OR REPLACE TEMP TABLE` (que vive en el espacio de sesión y no requiere permisos de dataset) o trabajar con operaciones DML sobre tablas persistentes predefinidas.

### 1.2 `missingDropStatement` (Omisión de DROP TABLE en Tablas Temporales)
* **Riesgo:** Tablas temporales pesadas creadas en scripts o Stored Procedures largos que no se eliminan al dejar de usarse mantienen ocupado el almacenamiento temporal de la sesión hasta por 24 horas.
* **Solución:** Agregar siempre `DROP TABLE IF EXISTS <tabla_temp>;` al finalizar el bloque donde la tabla temporal deja de ser necesaria.

### 1.4 `dynamicPredicate` (Construcción Dinámica de Filtros por Concatenación)
* **Riesgo:** Concatenar variables como texto dentro de `EXECUTE IMMEDIATE "SELECT ... WHERE id = '" || v_id || "'"` expone el código a Inyección SQL, errores por comillas y errores de casteo implícito.
* **Solución:** Usar consultas estáticas cuando el nombre de la tabla no sea dinámico, o parametrizar obligatoriamente `EXECUTE IMMEDIATE "... WHERE id = @p_id" USING v_id AS p_id;`.

### 1.28 `unhandledExceptionLogging` (Omisión de Captura de Error y Contexto en Excepciones)
* **Riesgo:** Bloques `EXCEPTION WHEN ERROR THEN` vacíos o que solo asignan banderas genéricas ocultan la causa raíz del fallo y dificultan el diagnóstico en producción.
* **Solución:** Capturar y registrar las variables del sistema en la bitácora de auditoría: `@@error.message`, `@@error.statement_text`, `@@error.stack_trace` y `@@script.job_id`.

### 1.48 `microDmlSaturation` (Ráfagas de DMLs Unitarios o Frecuentes sobre la Misma Tabla)
* **Riesgo:** Ejecutar múltiples sentencias `INSERT VALUES`, `UPDATE` o `DELETE` pequeñas de forma secuencial o concurrente agota las cuotas de trabajos DML por tabla, fragmenta el almacenamiento y provoca errores de serialización (`Could not serialize access to table due to concurrent update`).
* **Solución:** Consolidar todas las inserciones, actualizaciones y borrados del lote en una única sentencia `MERGE` o `INSERT INTO ... SELECT` masiva.

### 1.49 `deleteInsertWithoutTransaction` (Patrón `DELETE` + `INSERT` Fuera de Transacción)
* **Riesgo:** Ejecutar `DELETE FROM tabla WHERE fecha = v_fecha;` seguido de `INSERT INTO tabla SELECT ...;` sin control transaccional deja la partición vacía o inconsistente para los usuarios que consulten la tabla mientras corre el proceso o si el `INSERT` falla.
* **Solución:** Envolver ambas operaciones en `BEGIN TRANSACTION; ... COMMIT TRANSACTION;` con `ROLLBACK TRANSACTION;` en el bloque `EXCEPTION`, o consolidar en una única sentencia `MERGE`.

### 1.50 `fullTableDeleteInsteadOfTruncate` (Uso de `DELETE WHERE TRUE` para Vaciar Tablas)
* **Riesgo:** Ejecutar `DELETE FROM tabla WHERE TRUE` (o `1=1`) para limpiar una tabla de staging escanea la totalidad de los bytes y consume slots reescribiendo metadatos bloque por bloque.
* **Solución:** Utilizar `TRUNCATE TABLE proyecto.dataset.tabla;`, que vacía la tabla instantáneamente como operación de metadatos sin costo de escaneo.

### 1.51 `multipleScalarSetQueries` (Múltiples Consultas `SET var = (SELECT ...)` sobre la Misma Tabla)
* **Riesgo:** Asignar varias variables de control en un SP ejecutando una consulta independiente por cada variable (`SET v_min = (SELECT MIN(x) FROM t); SET v_max = (SELECT MAX(x) FROM t);`) multiplica por N los escaneos y la facturación sobre la misma tabla.
* **Solución:** Asignar todas las variables en un único escaneo mediante asignación de tupla: `SET (v_min, v_max, v_cnt) = (SELECT AS STRUCT MIN(x), MAX(x), COUNT(1) FROM t WHERE ...);`.

---

## PILAR 6: UDFs (User-Defined Functions)

### 1.29 `javascriptUDFs` (UDFs en JavaScript Innecesarias)
* **Riesgo:** Las UDFs en JavaScript (`LANGUAGE js`) requieren instanciar entornos V8 aislados, serializar datos entre el motor nativo y JS, y no se pueden optimizar ni vectorizar eficientemente en los slots.
* **Solución:** Reescribir la lógica utilizando funciones nativas y expresiones en SQL estándar (`LANGUAGE sql`).

### 1.30 `nonDeterministicUDFs` (Falta de Especificación de Determinismo y Subconsultas en UDFs)
* **Riesgo:** UDFs en JS sin `DETERMINISTIC` o UDFs en SQL que contienen referencias a tablas internas impiden que el optimizador reutilice resultados para entradas idénticas o aplique plegado de constantes (*constant folding*).
* **Solución:** Declarar `DETERMINISTIC` en UDFs de JavaScript de cálculo puro y mantener las UDFs de SQL libres de subconsultas a tablas físicas (pasar todos los insumos como argumentos escalares).

### 1.52 `udfInFilterOrJoinPredicate` (Invocación de UDFs sobre Columnas en `WHERE`, `JOIN ON` o `GROUP BY`)
* **Riesgo:** Evaluar una UDF sobre una columna dentro de `WHERE mi_udf(col) = 'X'` o `ON mi_udf(a.col) = b.col` desactiva la poda de particiones/clusters y fuerza la ejecución de la UDF sobre millones de filas antes de descartarlas.
* **Solución:** Filtrar primero usando predicados nativos SARGables para reducir el volumen de datos y aplicar la UDF únicamente en el `SELECT` final sobre el conjunto reducido.

### 1.53 `unbatchedRemoteUDFs` (Invocación de UDFs Remotas sin Deduplicación Previa)
* **Riesgo:** Invocar una Remote Function (Cloud Run / Cloud Functions) directamente sobre una columna con millones de filas y valores repetidos genera tráfico HTTP masivo, latencia de red, *throttling* y sobrecostos en el servicio externo.
* **Solución:** Extraer primero los valores únicos en una CTE (`SELECT DISTINCT col_entrada`), aplicar la UDF remota únicamente sobre el catálogo de valores únicos y hacer `LEFT JOIN` de regreso con la tabla principal.

---

## PILAR 7: Almacenamiento y FinOps en BigQuery

1. **Particionamiento Inteligente (Evitar Over-Partitioning):** Particionar tablas masivas (> 1 GB) por fecha (`DAY`, `MONTH` o `YEAR`) según su volumetría. Evitar particionar por día/hora tablas pequeñas donde cada partición pese menos de 10 MB (antipatrón *Small Partitions / Over-partitioning*), ya que el exceso de fragmentos degrada la lectura columnar y agota el límite de 10,000 particiones por tabla; en tablas < 1 GB, preferir únicamente clusterización.
2. **Clusterización Jerárquica:** Clusterizar por las 1 a 4 columnas más utilizadas en filtros de igualdad/rango (`WHERE`), llaves de `JOIN` y `GROUP BY`, ordenándolas de mayor a menor frecuencia de uso y evitando columnas de muy baja cardinalidad (ej. booleanos) en la primera posición.
3. **Vistas Materializadas y Desanidamiento de Vistas Lógicas:** Cuando se ejecutan cálculos agregados recurrentes sobre tablas base pesadas, crear una Vista Materializada (`CREATE MATERIALIZED VIEW`) para precalcular resultados incrementales. Evitar cadenas profundas de vistas lógicas anidadas (`VIEW` sobre `VIEW` sobre `VIEW`), ya que ocultan `JOINs` redundantes que se recalculan en cada petición de BI.
4. **Ciclo de Vida y Expiración Automática (TTL):** Configurar `partition_expiration_days` en tablas de eventos/logs y `default_table_expiration_days` en datasets de *staging* o desarrollo para evitar la acumulación indefinida de almacenamiento activo.
5. **Modelo de Facturación de Almacenamiento Físico (`PHYSICAL` vs `LOGICAL`):** En datasets con alta tasa de compresión (datos históricos, logs o tablas con cadenas repetitivas y poco uso de *Time Travel*), evaluar el cambio del dataset a `storage_billing_model = 'PHYSICAL'` y ajustar `max_time_travel_hours = 48` (en lugar de 168 horas) para reducir hasta en un 50-70% el costo de almacenamiento.
6. **Gobernanza de Costos por Consulta (`maximum_bytes_billed`):** Establecer cuotas preventivas por ejecución (`SET @@maximum_bytes_billed = ...;` o a nivel de proyecto/usuario) en entornos analíticos y pipelines automatizados para abortar antes de ejecutar cualquier consulta que, por un antipatrón accidental, intente escanear múltiples Terabytes.