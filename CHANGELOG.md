# Registro de cambios

## 3.0.0 — noviembre 2026

### Nuevo
- Un solo ítem "Pegar enlace" para todas las plataformas; pegar un enlace lo analiza solo.
- Trabajos en segundo plano (`/api/jobs`): la transcripción de enlaces corre en el servidor aunque se cierre la pestaña, se guarda sola en el historial y avisa con una notificación. Panel para pegar varios enlaces a la vez.
- Historial en SQLite (`/api/history`), con búsqueda en el texto sin importar tildes. Migración automática del historial guardado en el navegador.
- Visualizador "Ver y cortar": reproductor (YouTube embebido, copia liviana en 360p para otras plataformas o el archivo local) con texto sincronizado por frase y por palabra, línea de tiempo con forma de onda, marcado de recorte por selección de texto, arrastre o teclas I/O, vista previa del tramo y descarga.
- Recortes con subtítulos quemados y/o en formato vertical 9:16 (`/api/download` y `/api/clip-file`).
- Vista bilingüe: traducción frase por frase (`/api/translate-segments`).
- Tiempos por palabra (Groq `timestamp_granularities` y Whisper local `word_timestamps`), con plan B si la cuenta no los admite.
- Citas que se copian con atribución, minuto y enlace al segundo exacto.
- Botón "Original / Corregido" para ver el texto antes de la limpieza con IA.
- Mensajes de error con causa y qué hacer (`errors.py`); aviso al abrir si las cookies de YouTube vencieron.
- Estimación del tiempo de transcripción, búsqueda dentro de la transcripción, guardado automático al editar, arrastrar archivos a toda la ventana, diálogos propios en lugar de los del navegador y atajos de teclado (`?`).
- Aviso de que la identificación de hablantes es aproximada.

### Corregido
- El idioma elegido (ES / EN / Original) no se enviaba al transcribir un enlace: siempre se usaba español.
- Textos de estado en inglés ("Online", "Cookie Issues", "Offline").
- Las páginas web desconocidas se marcaban como YouTube en el historial.

## 2.x — revisión de seguridad (noviembre 2026)
- Cookies enviadas solo a su dominio, validación del Host (DNS rebinding), mantenimiento protegido, descargas parciales detectadas, control de fidelidad de la limpieza con IA, verificación TLS, frontend sin CDNs.
