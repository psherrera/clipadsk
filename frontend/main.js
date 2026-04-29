document.addEventListener('DOMContentLoaded', () => {
    // ── UI Elements ─────────────────────────────────────────────
    const videoUrlInput    = document.getElementById('video-url');
    const fetchBtn         = document.getElementById('fetch-info-btn');
    const loadingSpinner   = document.getElementById('loading-spinner');
    const qualityWarning   = document.getElementById('quality-warning');
    const videoInfoCard    = document.getElementById('video-info-card');
    const thumbnailImg     = document.getElementById('video-thumbnail');
    const titleEl          = document.getElementById('video-title');
    const uploaderEl       = document.getElementById('video-uploader');
    const descriptionEl    = document.getElementById('video-description');
    const formatSelect     = document.getElementById('format-select');
    const downloadBtn      = document.getElementById('download-btn');
    const downloadThumbBtn = document.getElementById('download-thumb-btn');
    const downloadProgress = document.getElementById('download-progress');
    const progressFill     = document.querySelector('.progress-fill');
    const progressText     = document.getElementById('progress-text');
    const progressPct      = document.getElementById('progress-percentage');
    const showTranscriptBtn = document.getElementById('show-transcript-btn');
    const transcriptSection = document.getElementById('transcript-section');
    const transcriptContent = document.getElementById('transcript-content');
    const copyTranscriptBtn = document.getElementById('copy-transcript-btn');
    const downloadTxtBtn   = document.getElementById('download-txt-btn');
    const appSubtitle      = document.getElementById('app-subtitle');
    const tabTitle         = document.getElementById('tab-title');
    const inputIcon        = document.getElementById('input-icon');

    // ── API – siempre local ──────────────────────────────────────
    const API_BASE = 'http://127.0.0.1:5000/api';

    // ── Estado ───────────────────────────────────────────────────
    let currentTab             = 'youtube';
    let currentMaxResThumbnail = '';

    // ── Navegación de pestañas ───────────────────────────────────
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            if (item.classList.contains('cursor-not-allowed')) return;

            navItems.forEach(i => {
                i.classList.remove('active', 'text-primary');
                i.classList.add('text-slate-500');
            });
            item.classList.add('active', 'text-primary');
            item.classList.remove('text-slate-500');

            currentTab = item.dataset.tab;

            if (currentTab === 'youtube') {
                tabTitle.textContent       = "YouTube Downloader";
                videoUrlInput.placeholder  = "Pega el enlace de YouTube aquí...";
                appSubtitle.textContent    = "Descarga videos de YouTube con la mejor calidad.";
                inputIcon.textContent      = "link";
            } else if (currentTab === 'instagram') {
                tabTitle.textContent       = "Instagram Downloader";
                videoUrlInput.placeholder  = "Pega el enlace de Instagram (Reel o Video) aquí...";
                appSubtitle.textContent    = "Descarga Reels y Videos de Instagram fácilmente.";
                inputIcon.textContent      = "photo_camera";
            }

            // Limpiar resultados al cambiar pestaña
            videoInfoCard.classList.add('hidden');
            videoUrlInput.value = '';
        });
    });

    // ── Obtener info del video ───────────────────────────────────
    fetchBtn.addEventListener('click', async () => {
        const url = videoUrlInput.value.trim();
        if (!url) {
            const platform = currentTab === 'youtube' ? 'YouTube' : 'Instagram';
            alert(`Por favor, pega una URL válida de ${platform}`);
            return;
        }

        // Resetear UI
        videoInfoCard.classList.add('hidden');
        qualityWarning.classList.add('hidden');
        loadingSpinner.classList.remove('hidden');
        transcriptSection.classList.add('hidden');
        showTranscriptBtn.classList.add('hidden');
        downloadTxtBtn.classList.add('hidden');
        titleEl.textContent       = '';
        uploaderEl.textContent    = '';
        descriptionEl.textContent = '';
        thumbnailImg.src          = '';
        formatSelect.innerHTML    = '';

        try {
            const response = await fetch(`${API_BASE}/video-info`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ url }),
            });
            const data = await response.json();

            if (data.error) {
                alert(data.error.replace(/\u001b\[[0-9;]*m/g, ''));
                return;
            }

            // Thumbnail
            if (data.thumbnail) {
                let thumbUrl = data.thumbnail;
                if (thumbUrl.startsWith('/')) {
                    thumbUrl = `http://127.0.0.1:5000${thumbUrl}`;
                }
                thumbnailImg.src          = thumbUrl;
                thumbnailImg.style.display = '';
            } else {
                thumbnailImg.style.display = 'none';
            }

            titleEl.textContent       = data.title;
            uploaderEl.textContent    = data.uploader;
            descriptionEl.textContent = data.description;
            currentMaxResThumbnail    = data.max_res_thumbnail;

            const durationEl = document.getElementById('video-duration');
            if (durationEl && data.duration) {
                const mins = Math.floor(data.duration / 60);
                const secs = data.duration % 60;
                durationEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
            }

            // Formatos
            formatSelect.innerHTML = '';
            data.formats.forEach(f => {
                const option      = document.createElement('option');
                option.value      = f.format_id;
                const size        = f.filesize
                    ? `(${(f.filesize / (1024 * 1024)).toFixed(1)} MB)`
                    : 'Tamaño N/D';
                option.textContent = `${f.label} – ${size}`;
                formatSelect.appendChild(option);
            });

            if (data.formats.length === 0) {
                const opt      = document.createElement('option');
                opt.value      = 'best';
                opt.textContent = 'Mejor calidad disponible';
                formatSelect.appendChild(opt);
            }

            if (!data.has_ffmpeg && currentTab === 'youtube') {
                qualityWarning.classList.remove('hidden');
            }

            showTranscriptBtn.classList.remove('hidden');
            videoInfoCard.classList.remove('hidden');
            videoInfoCard.classList.add('fade-in');

        } catch (error) {
            console.error('Error:', error);
            alert('Error al conectar con el backend. ¿Está corriendo en el puerto 5000?');
        } finally {
            loadingSpinner.classList.add('hidden');
        }
    });

    // ── Descargar video ──────────────────────────────────────────
    downloadBtn.addEventListener('click', async () => {
        const url      = videoUrlInput.value.trim();
        const formatId = formatSelect.value;

        downloadBtn.disabled = true;
        downloadProgress.classList.remove('hidden');

        let progress = 0;
        const interval = setInterval(() => {
            if (progress < 90) {
                progress += Math.random() * 5;
                updateProgress(Math.floor(progress), 'Procesando descarga...');
            }
        }, 800);

        function updateProgress(val, text) {
            progressFill.style.width    = `${val}%`;
            progressPct.textContent     = `${val}%`;
            if (text) progressText.textContent = text;
        }

        try {
            const response = await fetch(`${API_BASE}/download`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ url, format_id: formatId }),
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Error en la descarga');
            }

            clearInterval(interval);
            updateProgress(95, 'Preparando archivo...');

            const blob        = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a           = document.createElement('a');
            a.href            = downloadUrl;
            a.download        = `${(titleEl.textContent || 'video').substring(0, 40).trim()}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            a.remove();

            updateProgress(100, '¡Descarga completada!');
            setTimeout(() => {
                downloadProgress.classList.add('hidden');
                downloadBtn.disabled = false;
            }, 4000);

        } catch (error) {
            clearInterval(interval);
            console.error('Error:', error);
            alert(`Error: ${error.message}`);
            downloadProgress.classList.add('hidden');
        } finally {
            downloadBtn.disabled = false;
        }
    });

    // ── Transcripción ────────────────────────────────────────────
    showTranscriptBtn.addEventListener('click', async () => {
        const url = videoUrlInput.value.trim();
        transcriptSection.classList.remove('hidden');
        transcriptSection.classList.add('fade-in');
        transcriptContent.innerHTML = '<p class="animate-pulse">Extrayendo transcripción con IA... por favor espera.</p>';
        showTranscriptBtn.disabled  = true;

        try {
            const response = await fetch(`${API_BASE}/transcript`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ url }),
            });
            const data = await response.json();

            if (data.error) {
                transcriptContent.innerHTML = `
                    <div class="bg-red-500/10 p-4 rounded-xl border border-red-500/20 text-red-400">
                        Error: ${data.error.replace(/\u001b\[[0-9;]*m/g, '')}
                    </div>`;
            } else {
                let method = data.method || 'Desconocido';
                if (method.startsWith('whisper_local_')) {
                    const device = method.split('_').pop().toUpperCase();
                    method = `Whisper local (${device})`;
                } else {
                    const methodLabels = {
                        cache:           'Caché local',
                        subtitles:       'Subtítulos directos',
                        groq_whisper_v3: 'Groq Whisper v3',
                        whisper_local:   'Whisper local',
                    };
                    method = methodLabels[method] || method;
                }
                transcriptContent.innerHTML = `
                    <p class="mb-4">${data.transcript}</p>
                    <div class="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase
                                tracking-widest bg-white/5 py-1 px-3 rounded-full w-fit">
                        <span class="material-symbols-outlined text-xs">info</span>
                        Método: ${method}
                    </div>`;
                downloadTxtBtn.classList.remove('hidden');
                downloadTxtBtn.classList.add('fade-in');
            }
        } catch (error) {
            transcriptContent.innerHTML = '<p class="text-red-400">Error al conectar con el servidor.</p>';
        } finally {
            showTranscriptBtn.disabled = false;
        }
    });

    // ── Acciones auxiliares ──────────────────────────────────────
    downloadThumbBtn.addEventListener('click', () => {
        if (currentMaxResThumbnail) window.open(currentMaxResThumbnail, '_blank');
    });

    copyTranscriptBtn.addEventListener('click', () => {
        const text = transcriptContent.textContent.split('Método:')[0].trim();
        navigator.clipboard.writeText(text).then(() => {
            const orig = copyTranscriptBtn.innerHTML;
            copyTranscriptBtn.innerHTML = '<span class="material-symbols-outlined text-sm">check</span> COPIADO';
            setTimeout(() => { copyTranscriptBtn.innerHTML = orig; }, 2000);
        });
    });

    downloadTxtBtn.addEventListener('click', () => {
        const text = transcriptContent.textContent.split('Método:')[0].trim();
        const blob = new Blob([text], { type: 'text/plain' });
        const url  = window.URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `transcripcion_${(titleEl.textContent || 'video').substring(0, 20)}.txt`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    });
});
