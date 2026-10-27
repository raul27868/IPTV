# Diseño v15 — catálogo multimedia

## Objetivo
Organizar M3U en TV, Películas, Series, Eventos y Sin clasificar, con navegación serie → temporada → episodio. Conservar importación, búsqueda FTS5, favoritos, mpv y Google Cast.

## Principios
- Clasificación local y determinista según grupos, nombres y patrones; nunca asumir que es infalible.
- No descartar registros ni modificar URL, atributos M3U o favoritos.
- Mantener una sección Todos y otra Sin clasificar para los casos ambiguos.
- No confundir deportes con eventos deportivos temporales.
- Migrar SQLite sin perder datos existentes.

## Reglas propuestas en orden
1. Series: patrones claros de temporada y episodio (S01E02, 1x02) o grupos explícitos de series; extraer serie, temporada y episodio cuando se pueda.
2. Películas: grupos o prefijos explícitos de cine, películas, VOD o movies. Un año en el título no basta.
3. Eventos: grupos etiquetados claramente como eventos temporales; no clasificar automáticamente la TV deportiva como eventos.
4. TV: grupos explícitos de canales/TV/live u otros indicios fuertes.
5. Sin clasificar: evidencia insuficiente.

## Esquema SQLite propuesto
Añadir a channels: media_type (tv/movie/series/event/unknown), series_title, season_number, episode_number, classification_rule. Crear índices por categoría y serie, conservando FTS5 y las tablas de favoritos. Migración compatible con el catálogo v14.

## Interfaz
- Selector Todos | TV | Películas | Series | Eventos | Sin clasificar.
- TV / Películas / Eventos: grupos, búsqueda, paginación, favoritos.
- Series: títulos agrupados; abrir una serie muestra temporadas y episodios.
- Contadores por tipo y método de clasificación consultable.

## Pruebas
- Importación de aproximadamente 258.000 registros, contadores consistentes, sin pérdida de favoritos.
- Migración v14 → v15 y reinicio persistente.
- Patrones S01E02 y 1x02, nombres ambiguos, acentos, episodios sin metadatos.
- Reproducción mpv y Google Cast y filtros.
- CI y pruebas reales en Ubuntu antes de fusionar.

## Pospuesto
EPG, carátulas externas, scraping y clasificación mediante IA.
