# GUÍA UNIFICADA: ANTIPATRONES SQL Y BUENAS PRÁCTICAS EN BIGQUERY

Esta guía documenta los 17 antipatrones oficiales de SQL en Google Cloud BigQuery, sus riesgos técnicos y financieros (FinOps / DataOps) y las soluciones recomendadas.

---

## 1. Catálogo Oficial de 17 Antipatrones SQL

### 1.1 `selectStar` (Uso Indiscriminado de SELECT *)
* **Riesgo:** BigQuery factura por bytes leídos. `SELECT *` lee todas las columnas físicas de la tabla columnar, multiplicando costos y saturando memoria.
* **Solución:** Proyectar explícitamente solo las columnas requeridas (`SELECT col1, col2`).

### 1.2 `missingDropStatement` (Omisión de DROP TABLE en Tablas Temporales)
* **Riesgo:** Tablas temporales creadas en scripts o Stored Procedures que no se liberan consumen espacio de sesión y saturan metadatos.
* **Solución:** Agregar siempre `DROP TABLE IF EXISTS <tabla_temp>;` al terminar el bloque de procesamiento.

### 1.3 `droppedPersistentTable` (Uso de Tablas Físicas como Temporales)
* **Riesgo:** Crear y borrar repetidamente tablas físicas persistentes en procesos batch satura operaciones DDL de metadatos de GCP.
* **Solución:** Usar `CREATE OR REPLACE TEMP TABLE` o trabajar con operaciones DML (`INSERT`, `MERGE`) en tablas persistentes predefinidas.

### 1.4 `dynamicPredicate` (Construcción Dinámica de Filtros por Concatenación)
* **Riesgo:** Concatenar strings en `EXECUTE IMMEDIATE` genera vulnerabilidades de Inyección SQL y desactiva el optimizador de consultas.
* **Solución:** Usar consultas estáticas parametrizadas o la cláusula `USING` con tipos de datos estrictos.

### 1.5 `joinOrder` (Cruces Implícitos mediante Comas)
* **Riesgo:** `FROM t1, t2 WHERE t1.id = t2.id` reduce la legibilidad y puede inducir al planificador a generar productos cartesianos no deseados.
* **Solución:** Usar sintaxis ANSI estándar explícita: `FROM t1 INNER JOIN t2 ON t1.id = t2.id`.

### 1.6 `latestRecord` (Obtención Ineficiente del Último Registro con ORDER BY ... LIMIT 1)
* **Riesgo:** `ORDER BY col DESC LIMIT 1` fuerza un ordenamiento global en un único slot distribuidor.
* **Solución:** Usar funciones de ventana analíticas: `QUALIFY ROW_NUMBER() OVER(PARTITION BY entidad_id ORDER BY fecha DESC) = 1`.

### 1.7 `multipleCTES` (Exceso de CTEs Fragmentadas o Re-ejecutadas)
* **Riesgo:** Las cláusulas `WITH` (CTEs) no se materializan por defecto y se recalculan cada vez que son referenciadas en la consulta.
* **Solución:** Si una transformación intermedia se consulta más de una vez, materializarla en `CREATE TEMP TABLE` o simplificar el pipeline.

### 1.8 `orderByWithoutLimit` (Ordenamiento Masivo en CTEs Intermedias)
* **Riesgo:** Ordenar datos dentro de subconsultas o CTEs intermedias sin `LIMIT` desperdicia CPU y memoria en ordenamientos inútiles.
* **Solución:** Eliminar `ORDER BY` en subconsultas intermedias; ordenar únicamente en la consulta final cuando sea estrictamente necesario.

### 1.9 `stringComparison` (Comparación de Cadenas sin Normalización)
* **Riesgo:** Inconsistencias lógicas y fallas en filtros por diferencias de mayúsculas/minúsculas o colación.
* **Solución:** Normalizar explícitamente: `LOWER(columna) = LOWER('valor')`.

### 1.10 `subqueryInFilterWithoutAgg` (Subconsultas en WHERE IN sin Agregación)
* **Riesgo:** `WHERE id IN (SELECT id FROM ...)` puede inhibir la paralelización óptima.
* **Solución:** Reescribir utilizando `INNER JOIN` o `WHERE EXISTS (...)`.

### 1.11 `whereOrder` (División Insegura / Orden de Evaluación en WHERE)
* **Riesgo:** BigQuery evalúa predicados en paralelo sin orden secuencial garantizado, lo que causa errores por división entre cero en tiempo de ejecución.
* **Solución:** Usar siempre `SAFE_DIVIDE(a, b)` o `NULLIF(b, 0)`.

### 1.12 `partitionPruningDisabled` (Deshabilitación de Poda de Particiones por Funciones)
* **Riesgo:** Usar funciones sobre columnas de partición (ej. `DATE(timestamp_col) = '2026-06-13'`) anula el índice de partición y fuerza un *Full Table Scan*.
* **Solución:** Filtrar directamente sobre el campo de partición: `timestamp_col >= '2026-06-13 00:00:00' AND timestamp_col < '2026-06-14 00:00:00'`.

### 1.13 `skewedJoinKeys` (Cruces sobre Claves Desbalanceadas o Nulas)
* **Riesgo:** Unir tablas sobre claves con alta concentración de nulos o comodines (`'99999'`, `NULL`) sobrecarga un solo slot de cómputo (*data skew*).
* **Solución:** Filtrar o aislar valores nulos y comodines antes del cruce (`WHERE clave IS NOT NULL AND clave != '99999'`).

### 1.14 `selfJoin` (Uso de Self-JOINs en Lugar de Funciones de Ventana)
* **Riesgo:** Unir una tabla consigo misma para comparar filas consecutivas duplica los bytes leídos.
* **Solución:** Usar funciones de ventana: `LAG()`, `LEAD()`, `FIRST_VALUE()`.

### 1.15 `prematureRegexp` (Evaluación Prematura de Expresiones Regulares)
* **Riesgo:** Evaluar expresiones regulares costosas (`REGEXP_CONTAINS`) antes de aplicar filtros escalares rápidos satura la CPU.
* **Solución:** Colocar primero en el `WHERE` los filtros de igualdad, partición o rango, y al final las funciones `REGEXP`.

### 1.16 `redundantUnionAll` (Repetición de Consultas con UNION ALL)
* **Riesgo:** Repetir lecturas de la misma tabla física en múltiples ramas de `UNION ALL` multiplica linealmente el costo por escaneo.
* **Solución:** Consolidar en una sola pasada usando `CASE WHEN` y agregaciones condicionales (`SUM(CASE WHEN ...)` o `COUNTIF(...)`) agrupadas por `GROUP BY`.

### 1.17 `multipleUnnests` (Múltiples Desanidamientos de Arreglos UNNEST)
* **Riesgo:** Subconsultas correlacionadas desanidando el mismo array repetidamente disparan el costo computacional.
* **Solución:** Realizar un único `CROSS JOIN UNNEST(array)` y utilizar agregaciones condicionales (`COUNTIF(...)`).

---

## 2. Recomendaciones de Almacenamiento y FinOps en BigQuery

1. **Particionamiento:** Particionar tablas masivas (>100k filas) por día/mes para acotar el volumen escaneado.
2. **Clusterización:** Clusterizar por las 1 a 4 columnas más utilizadas en filtros de igualdad y llaves de JOIN.
3. **Vistas Materializadas:** Cuando se ejecutan cálculos agregados recurrentes sobre tablas base pesadas, crear una Vista Materializada (`CREATE MATERIALIZED VIEW`) para precalcular resultados y no saturar slots.
