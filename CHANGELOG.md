# Registro de cambios

## 3.4.0 — 2026-11-13

### Nuevo
- **Glosario de nombres propios** (Configuración → Glosario): un nombre por línea; `Yemini = Gemini` corrige siempre esa forma. Se le pasa a Whisper (Groq y local) como pista, se agrega como regla a la limpieza con IA y se aplica sobre el texto y los segmentos al terminar.
- **Reemplazar** en la transcripción: busca una palabra o frase (palabra completa, sin importar mayúsculas), cuenta cuántas veces aparece, la cambia en el texto y en los tiempos, lo guarda en el historial y ofrece sumarlo al glosario.
- **Renombrar hablantes**: en el resultado de "Hablantes", un botón por cada nombre cambia ese nombre en todo el diálogo.
- **Word**: minuto al comienzo de cada párrafo, "Citas destacadas" (si se corrió "Citas") y "Diálogo por hablantes" al final (si se corrió "Hablantes", con los nombres ya renombrados).
- **Probar API Key** (Configuración): comprueba con Groq que la key funcione y que haya Whisper disponible; también se prueba sola al guardar.
- **Aviso de versión nueva**: consulta GitHub como mucho cada 12 horas y marca el botón de actualizar.
- **Uso desde el celular** (mismo Wi-Fi): se activa y desactiva con un botón en Configuración → "Usar desde el celular" (la app se reinicia sola; Windows pide permiso de administrador solo la primera vez, porque la regla del firewall queda creada); `ACTIVAR_CELULAR.bat` hace lo mismo desde fuera de la app y abre Clipadsk a la red con un PIN de 6 dígitos y abre el puerto en el firewall (solo redes privadas); `DESACTIVAR_CELULAR.bat` lo apaga. En Configuración aparece el QR (se dibuja en el navegador, sin librerías extra), la dirección y el PIN. Desde la PC no se pide PIN; desde el celular se pide una vez (30 días), con límite de intentos. Actualizar la app y cambiar ajustes quedan solo en la PC.

### Cambios
- Íconos PNG (192, 512 y maskable) y manifiesto corregido (nombre "Clipadsk") para "Agregar a la pantalla principal" en Android. El manifiesto y los íconos se sirven sin PIN.
- `PATCH /api/history/{id}` acepta `segments` (para que reemplazar no deje tiempos con el texto viejo).
- `require_admin` permite el mantenimiento desde la propia PC aunque Clipadsk esté abierto a la red con PIN.
- Copiar al portapapeles funciona también desde el celular (en http no existe `navigator.clipboard`).

## 3.3.0 — 2026-11-12

- **Análisis del copy**: al analizar un enlace (Instagram, TikTok, YouTube…) aparece el texto completo de la publicación con un botón "Analizar el copy": mensaje central, tono y estrategia, recursos (gancho, hashtags, menciones, llamados a la acción), afirmaciones para verificar, lo que no dice y cómo usarlo en una nota. No hace falta transcribir; si ya hay transcripción o texto de las imágenes, se usa como contexto. También está como botón "Copy" en las herramientas periodísticas.
- **Cookies protegidas**: yt-dlp y gallery-dl trabajan con una copia del archivo de cookies; antes podían borrar la sesión de Instagram del archivo original.
- La interfaz se sirve sin caché (no queda una versión vieja después de actualizar).
- Acceso directo al Escritorio con `CREAR_ACCESO_DIRECTO.bat`; carpeta ordenada.

## 3.2.0 — noviembre 2026

### Nuevo
- **Listas y canales de YouTube:** al pegar una lista o un canal aparecen sus videos con casillas para elegir; los elegidos se transcriben en fila, en segundo plano.
- **Grabar vivos:** si el enlace está en vivo aparece "Grabar el vivo" (desde ahora o desde el principio, y transcribir al terminar). Graba hasta que termina la transmisión, se detiene desde el panel de trabajos o llega al máximo de horas. Queda en `grabaciones` como .mp4; si se corta en el medio lo grabado igual sirve.
- **Configuración → Funciones extra:**
  - Subtítulos de YouTube: usarlos siempre, solo los del autor o nunca (transcribir siempre).
  - Comentarios de YouTube: botón "Comentarios" con los más votados o los más nuevos, búsqueda y descarga en .txt.
  - Vigilar canales: avisa (navegador y notificación de Windows) cuando un canal o una lista sube un video nuevo; opcionalmente lo transcribe solo.
  - Corte automático de las grabaciones.
- Ajustes guardados en la PC (`/api/settings`), compartidos entre navegadores.

## 3.1.0 — noviembre 2026

### Nuevo
- **Galería de carruseles de Instagram:** al pegar un carrusel se ven todas las fotos y videos en miniatura. Se puede elegir una, varias o todas y bajarlas sueltas o en un .zip. Doble clic abre la foto grande, con flechas para recorrer y "Descargar esta". Los carruseles se detectan también con instaloader (antes solo se ofrecía la primera imagen) y con yt-dlp cuando el carrusel tiene varios videos.
- **Clipa.exe nuevo** (`CREAR_EXE.bat`): si en la carpeta hay una instalación (`backend\venv`) la usa, así el exe corre siempre el código actual y se actualiza desde la app. Sin instalación funciona solo, con los datos en `clipadsk_datos`. Si Clipadsk ya está abierto, solo abre el navegador.
- **Clipa para Claude** (`INSTALAR_MCP.bat`): servidor MCP para Claude Desktop con herramientas para transcribir enlaces y archivos, buscar y leer el historial, traducir, resumir, sacar citas y descargar. El trabajo lo hace Clipa en la PC; a Claude le llega solo el texto.
- gallery-dl también funciona como biblioteca (el exe no trae el programa gallery-dl).

### Cambios
- Rutas de datos configurables (`CLIPA_HOME`, `CLIPA_DATA_DIR`) para el exe autónomo. En el exe autónomo las actualizaciones desde la app avisan que hay que regenerarlo.

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
