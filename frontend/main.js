/**
 * Clipadsk - Frontend v2.0
 * Herramienta de transcripción para periodistas y comunicadores.
 * Mejoras: WhatsApp upload, TikTok/Twitter/Facebook, herramientas periodísticas, historial.
 */
document.addEventListener('DOMContentLoaded', () => {

    // ─── FIRST-RUN REDIRECT ──────────────────────────────────────────────────────
    // Si el usuario nunca completó el setup, redirigir antes de cargar nada
    if (!localStorage.getItem('clipadsk_setup_done')) {
        window.location.replace('setup.html');
        return; // Detener el resto del script
    }


    // ─── UI ELEMENTS ────────────────────────────────────────────────────────────
    const videoUrlInput        = document.getElementById('video-url');
    const fetchBtn             = document.getElementById('fetch-info-btn');
    const loadingSpinner       = document.getElementById('loading-spinner');
    const qualityWarning       = document.getElementById('quality-warning');
    const videoInfoCard        = document.getElementById('video-info-card');
    const thumbnailImg         = document.getElementById('video-thumbnail');
    const titleEl              = document.getElementById('video-title');
    const uploaderEl           = document.getElementById('video-uploader');
    const descriptionEl        = document.getElementById('video-description');
    const formatSelect         = document.getElementById('format-select');
    const downloadBtn          = document.getElementById('download-btn');
    const downloadThumbBtn     = document.getElementById('download-thumb-btn');
    const downloadProgress     = document.getElementById('download-progress');
    const progressFill         = document.querySelector('.progress-fill');
    const progressText         = document.getElementById('progress-text');
    const progressPercentage   = document.getElementById('progress-percentage');
    const showTranscriptBtn    = document.getElementById('show-transcript-btn');
    const transcriptSection    = document.getElementById('transcript-section');
    const transcriptContent    = document.getElementById('transcript-content');
    const copyTranscriptBtn    = document.getElementById('copy-transcript-btn');
    const downloadTxtBtn       = document.getElementById('download-txt-btn');
    const downloadSrtBtn       = document.getElementById('download-srt-btn');
    const appSubtitle          = document.getElementById('app-subtitle');
    const tabTitle             = document.getElementById('tab-title');
    const inputIcon            = document.getElementById('input-icon');
    const clearUrlBtn          = document.getElementById('clear-url-btn');
    const statusDot            = document.getElementById('status-dot');
    const statusText           = document.getElementById('status-text');
    const pwaInstallBtn        = document.getElementById('pwa-install-btn');
    const navItems             = document.querySelectorAll('.nav-item');
    
    // GROQ API KEY ELEMENTS
    const groqApiKeyInput      = document.getElementById('groq-api-key-input');
    const saveApiKeyBtn        = document.getElementById('save-api-key-btn');

    // ─── CONFIG ─────────────────────────────────────────────────────────────────
    const isLocal      = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:';
    const isSharedPort = window.location.port === '5000' || window.location.port === '10000';
    const API_BASE     = (isLocal && !isSharedPort) ? 'http://127.0.0.1:5000/api' : '/api';

    // UID unico para cada sesion de la pagina (para logs y progreso)
    const uid = Math.random().toString(36).substring(2, 10);
    
    let currentTab             = 'youtube';
    let currentTranscript      = '';
    let currentSrt             = '';
    let currentMaxResThumbnail = '';
    let currentSegments        = [];

    // ─── SEGURIDAD: escapeHtml para evitar XSS en datos de usuario ───────────────
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // AbortController activo para fetches cancelables
    let activeAbortController = null;
    // Flag para evitar doble polling en transcripción
    let isTranscribing = false;
    let activeTranscriptPollInterval = null;

    // ─── PLATFORM DETECTION ─────────────────────────────────────────────────────
    const PLATFORMS = {
        youtube:   { hosts: ['youtube.com', 'youtu.be'],             icon: 'subscriptions', label: 'YouTube',   placeholder: 'Pega el enlace de YouTube...' },
        instagram: { hosts: ['instagram.com'],                        icon: 'photo_library', label: 'Instagram', placeholder: 'Pega el enlace del Reel o Video...' },
        redes:     { hosts: ['tiktok.com', 'vm.tiktok.com', 'twitter.com', 'x.com', 't.co', 'facebook.com', 'fb.watch', 'fb.com'], icon: 'share', label: 'Redes (TikTok/X/FB)', placeholder: 'Pega enlace de TikTok, X o Facebook...' },
        whatsapp:  { hosts: [],                                       icon: 'mic',           label: 'WhatsApp',  placeholder: 'Sube un audio de WhatsApp (.ogg/.mp3)' },
        video:     { hosts: [],                                       icon: 'video_file',    label: 'Video',     placeholder: 'Subí un video local (.mp4/.mov)' },
        history:   { hosts: [],                                       icon: 'settings',      label: 'Configuracion', placeholder: '' },
    };

    function detectPlatformFromUrl(url) {
        for (const [key, cfg] of Object.entries(PLATFORMS)) {
            if (cfg.hosts.some(h => url.includes(h))) return key;
        }
        return 'youtube';
    }

    // ─── HISTORY ─────────────────────────────────────────────────────────────────
    const HISTORY_KEY = 'clipadsk_history';
    const GROQ_KEY_STORE = 'clipadsk_groq_api_key';

    if (groqApiKeyInput) {
        groqApiKeyInput.value = localStorage.getItem(GROQ_KEY_STORE) || '';
    }
    
    saveApiKeyBtn?.addEventListener('click', () => {
        const key = groqApiKeyInput?.value.trim();
        if (key) {
            localStorage.setItem(GROQ_KEY_STORE, key);
            showToast('API Key guardada correctamente', 'success');
        } else {
            localStorage.removeItem(GROQ_KEY_STORE);
            showToast('API Key eliminada', 'info');
        }
    });

    // ─── CLEAR DOWNLOADS ─────────────────────────────────────────────────────────
    const clearDownloadsBtn = document.getElementById('clear-downloads-btn');
    clearDownloadsBtn?.addEventListener('click', async () => {
        if (!confirm('¿Estás seguro que deseas borrar todos los archivos descargados? Esto liberará espacio en el disco duro de la computadora.')) return;
        
        const originalText = clearDownloadsBtn.innerHTML;
        clearDownloadsBtn.innerHTML = '<div class="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin"></div> Borrando...';
        clearDownloadsBtn.disabled = true;

        try {
            const r = await fetch(`${API_BASE}/clear-downloads`, { method: 'DELETE' });
            const data = await r.json();
            if (r.ok) showToast('Descargas borradas correctamente, espacio liberado', 'success');
            else throw new Error(data.detail || 'Error al borrar descargas');
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            clearDownloadsBtn.innerHTML = originalText;
            clearDownloadsBtn.disabled = false;
        }
    });

    function getHistory() {
        try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
        catch { return []; }
    }

    function saveToHistory(entry) {
        const history = getHistory();
        const idx = history.findIndex(h => h.url === entry.url);
        if (idx !== -1) history.splice(idx, 1);
        history.unshift({ ...entry, date: new Date().toISOString() });
        if (history.length > 50) history.pop();
        localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        if (currentTab === 'history') renderHistory();
    }

    function renderHistory() {
        const container = document.getElementById('history-list');
        if (!container) return;
        const history = getHistory();

        if (history.length === 0) {
            container.innerHTML = `
                <div class="text-center py-16 text-slate-500">
                    <span class="material-symbols-outlined text-5xl mb-4 block opacity-30">history</span>
                    <p class="text-sm">Aún no hay transcripciones guardadas.</p>
                    <p class="text-xs mt-1 opacity-60">Se guardan automáticamente al transcribir.</p>
                </div>`;
            return;
        }

        container.innerHTML = history.map((item, i) => {
            const date = new Date(item.date).toLocaleDateString('es-AR', { day:'2-digit', month:'short', year:'numeric' });
            const platformIcon = PLATFORMS[item.platform]?.icon || 'link';
            // escapeHtml para prevenir XSS con datos del historial
            const safeTitle   = escapeHtml(item.title || item.url);
            const preview     = escapeHtml(item.transcript ? item.transcript.substring(0, 140) + '...' : 'Sin transcripcion');
            return `
            <div class="glass rounded-2xl p-5 space-y-3 fade-in">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="material-symbols-outlined text-primary text-lg flex-shrink-0">${platformIcon}</span>
                        <span class="text-white font-semibold text-sm truncate">${safeTitle}</span>
                    </div>
                    <span class="text-slate-500 text-[10px] flex-shrink-0 font-mono">${date}</span>
                </div>
                ${item.transcript ? `
                <p class="text-slate-400 text-xs leading-relaxed line-clamp-2">${preview}</p>
                <div class="flex gap-2 flex-wrap">
                    <button onclick="window._hist.load(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-primary/20 text-primary px-3 py-1.5 rounded-full hover:bg-primary/30 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">visibility</span> Ver
                    </button>
                    <button onclick="window._hist.copy(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-accent/20 text-accent px-3 py-1.5 rounded-full hover:bg-accent/30 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">content_copy</span> Copiar
                    </button>
                    <button onclick="window._hist.download(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-white/5 text-slate-300 px-3 py-1.5 rounded-full hover:bg-white/10 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">download</span> .txt
                    </button>
                    ${item.srt ? `
                    <button onclick="window._hist.downloadSrt(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-emerald-500/10 text-emerald-300 px-3 py-1.5 rounded-full hover:bg-emerald-500/25 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">subtitles</span> .srt
                    </button>
                    ` : ''}
                    <button onclick="window._hist.remove(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-red-500/10 text-red-400 px-3 py-1.5 rounded-full hover:bg-red-500/20 transition-all flex items-center gap-1 ml-auto">
                        <span class="material-symbols-outlined text-xs">delete</span>
                    </button>
                </div>` : ''}
            </div>`;
        }).join('');
    }

    window._hist = {
        load: (i) => {
            const item = getHistory()[i];
            if (!item) return;
            switchTab(item.platform || 'youtube');
            if (videoUrlInput && !item.url.startsWith('whatsapp:') && !item.url.startsWith('video:')) {
                videoUrlInput.value = item.url;
                clearUrlBtn?.classList.remove('hidden');
            }
            currentTranscript = item.transcript;
            currentSrt = item.srt || '';
            currentSegments = item.segments || [];
            
            renderTranscript(item.transcript, 'cache', item.srt, item.segments);
            downloadTxtBtn?.classList.remove('hidden');
            
            if (titleEl) titleEl.textContent = item.title || 'Transcripción';
            if (videoInfoCard && !item.url.startsWith('whatsapp:') && !item.url.startsWith('video:')) {
                videoInfoCard.classList.remove('hidden');
            }
            showToast('Transcripción cargada', 'success');
        },
        copy: (i) => {
            const item = getHistory()[i];
            if (item?.transcript) { navigator.clipboard.writeText(item.transcript); showToast('Copiado', 'success'); }
        },
        download: (i) => {
            const item = getHistory()[i];
            if (!item?.transcript) return;
            const blob = new Blob([item.transcript], { type: 'text/plain' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${(item.title || 'transcripcion').substring(0, 30)}.txt`;
            a.click();
        },
        downloadSrt: (i) => {
            const item = getHistory()[i];
            if (!item?.srt) return;
            const blob = new Blob([item.srt], { type: 'text/srt;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${(item.title || 'subtitulos').substring(0, 30)}.srt`;
            a.click();
            URL.revokeObjectURL(a.href);
        },
        remove: (i) => {
            const history = getHistory();
            history.splice(i, 1);
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
            renderHistory();
        }
    };

    // TAB SWITCHING
    function switchTab(tab) {
        currentTab = tab;
        navItems.forEach(i => { i.classList.remove('active', 'text-primary'); i.classList.add('text-slate-500'); });
        const activeNav = document.querySelector(`[data-tab="${tab}"]`);
        if (activeNav) { activeNav.classList.add('active', 'text-primary'); activeNav.classList.remove('text-slate-500'); }

        const cfg         = PLATFORMS[tab];
        const mainSection = document.getElementById('main-input-section');
        const waSection   = document.getElementById('whatsapp-section');
        const vidSection  = document.getElementById('video-section');
        const histSection = document.getElementById('history-section');

        mainSection?.classList.toggle('hidden', tab === 'whatsapp' || tab === 'video' || tab === 'history');
        waSection?.classList.toggle('hidden', tab !== 'whatsapp');
        vidSection?.classList.toggle('hidden', tab !== 'video');
        histSection?.classList.toggle('hidden', tab !== 'history');

        // Limpiar toda la interfaz al cambiar (o re-clicar) una pestana
        videoInfoCard?.classList.add('hidden');
        transcriptSection?.classList.add('hidden');
        showTranscriptBtn?.classList.add('hidden');
        downloadTxtBtn?.classList.add('hidden');
        qualityWarning?.classList.add('hidden');
        downloadProgress?.classList.add('hidden');
        clearUrlBtn?.classList.add('hidden');

        // Limpiar secciones de upload (WA y Video)
        document.getElementById('wa-result')?.classList.add('hidden');
        document.getElementById('vid-result')?.classList.add('hidden');
        document.getElementById('vid-progress')?.classList.add('hidden');

        // Herramientas periodisticas y chat
        const toolsWrapper = document.getElementById('journalist-tools-wrapper');
        if (toolsWrapper) { toolsWrapper.innerHTML = ''; toolsWrapper.classList.add('hidden'); }
        document.getElementById('ai-chat-section')?.classList.add('hidden');
        const chatHistory = document.getElementById('chat-history');
        if (chatHistory) chatHistory.innerHTML = '';
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.value = '';

        // Eliminar el panel de recorte inline para que se recree en la próxima transcripción
        document.getElementById('inline-clip-tool')?.remove();

        // Estado interno
        currentTranscript = '';
        currentSrt = '';
        currentMaxResThumbnail = '';
        downloadSrtBtn?.classList.add('hidden');

        if (cfg) {
            if (tabTitle)    tabTitle.textContent    = tab === 'history' ? 'Configuracion y Guardados' : `${cfg.label} Transcriptor`;
            if (appSubtitle) appSubtitle.textContent = tab === 'history' ? 'Ajustes, claves de API y transcripciones locales.' : `Transcribi contenido de ${cfg.label} con IA.`;
            if (inputIcon)   inputIcon.textContent   = cfg.icon;
            if (videoUrlInput && tab !== 'history') videoUrlInput.placeholder = cfg.placeholder;
        }

        if (tab === 'history') renderHistory();
        if (videoUrlInput) videoUrlInput.value = '';
    }


    navItems.forEach(item => {
        item.addEventListener('click', () => {
            if (item.classList.contains('cursor-not-allowed')) return;
            switchTab(item.dataset.tab);
        });
    });



    // ─── SERVER STATUS ───────────────────────────────────────────────────────────
    const updateStatusUI = (status) => {
        statusDot.className = 'w-2 h-2 rounded-full';
        statusText.className = 'text-xs font-medium';
        if (status === 'online') {
            statusDot.classList.add('bg-emerald-500', 'shadow-[0_0_8px_rgba(16,185,129,0.5)]');
            statusText.classList.add('text-emerald-500');
            statusText.textContent = 'Online';
        } else if (status === 'issues') {
            statusDot.classList.add('bg-amber-500', 'animate-pulse');
            statusText.classList.add('text-amber-500');
            statusText.textContent = 'Cookie Issues';
        } else {
            statusDot.classList.add('bg-slate-600');
            statusText.classList.add('text-slate-500');
            statusText.textContent = 'Offline';
        }
    };
    const checkServerStatus = async () => {
        try {
            const r = await fetch(`${API_BASE}/health/cookies`);
            if (r.ok) { const d = await r.json(); updateStatusUI(d.status === 'ok' ? 'online' : 'issues'); }
            else updateStatusUI('offline');
        } catch { updateStatusUI('offline'); }
    };
    setTimeout(checkServerStatus, 1500);
    setInterval(checkServerStatus, 60000);

    // ─── CLEAR INPUT ─────────────────────────────────────────────────────────────
    videoUrlInput?.addEventListener('input', () => {
        clearUrlBtn?.classList.toggle('hidden', videoUrlInput.value.trim().length === 0);
    });
    clearUrlBtn?.addEventListener('click', () => {
        videoUrlInput.value = '';
        clearUrlBtn.classList.add('hidden');
        videoUrlInput.focus();
        videoInfoCard?.classList.add('hidden');
    });

    // ─── PWA INSTALL ─────────────────────────────────────────────────────────────
    let deferredPrompt;
    window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredPrompt = e; pwaInstallBtn?.classList.remove('hidden'); });
    pwaInstallBtn?.addEventListener('click', async () => {
        if (!deferredPrompt) return;
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        if (outcome === 'accepted') pwaInstallBtn.classList.add('hidden');
        deferredPrompt = null;
    });
    window.addEventListener('appinstalled', () => { pwaInstallBtn?.classList.add('hidden'); deferredPrompt = null; });

    // ─── SHARE TARGET ────────────────────────────────────────────────────────────
    (() => {
        const params = new URLSearchParams(window.location.search);
        const shared = params.get('url') || params.get('text') || params.get('title') || '';
        const match  = shared.match(/(https?:\/\/[^\s]+)/);
        if (match) {
            const cleanUrl = match[0];
            switchTab(detectPlatformFromUrl(cleanUrl));
            if (videoUrlInput) { videoUrlInput.value = cleanUrl; clearUrlBtn?.classList.remove('hidden'); }
            if (localStorage.getItem('app_logged_in') === 'true') setTimeout(() => fetchBtn?.click(), 700);
        }
    })();

    // ─── FETCH VIDEO INFO ────────────────────────────────────────────────────────
    fetchBtn?.addEventListener('click', async () => {
        const url = videoUrlInput?.value.trim();
        if (!url) { showToast('Pega una URL valida primero', 'error'); return; }

        videoInfoCard?.classList.add('hidden');
        qualityWarning?.classList.add('hidden');
        loadingSpinner?.classList.remove('hidden');
        transcriptSection?.classList.add('hidden');
        showTranscriptBtn?.classList.add('hidden');
        downloadTxtBtn?.classList.add('hidden');
        downloadSrtBtn?.classList.add('hidden');
        currentSrt = '';
        
        const chatInputBox = document.getElementById('chat-input');
        if (chatInputBox) chatInputBox.value = '';
        
        const chatResponseBox = document.getElementById('chat-response');
        if (chatResponseBox) {
            chatResponseBox.innerHTML = '';
            chatResponseBox.classList.add('hidden');
        }
        
        document.querySelectorAll('[id$="-ai-output"]').forEach(el => {
            el.innerHTML = '';
            el.classList.add('hidden');
        });

        const detected = detectPlatformFromUrl(url);
        if (detected !== currentTab && detected !== 'youtube') switchTab(detected);

        try {
            const r = await fetch(`${API_BASE}/video-info`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || e.error || 'Error en el servidor'); }
            const data = await r.json();
            if (data.error) throw new Error(data.error.replace(/\u001b\[[0-9;]*m/g, ''));
            if (!data.formats?.length) throw new Error('No se encontraron formatos para este video.');

            if (data.thumbnail) {
                let t = data.thumbnail;
                if (t.startsWith('/api/')) t = window.location.origin + t;
                thumbnailImg.src = t; thumbnailImg.style.display = '';
            } else { thumbnailImg.style.display = 'none'; }

            titleEl.textContent    = data.title;
            uploaderEl.textContent = data.uploader;
            descriptionEl.textContent = data.description;
            currentMaxResThumbnail = data.max_res_thumbnail;

            const durationEl = document.getElementById('video-duration');
            if (durationEl && data.duration) {
                const m = Math.floor(data.duration / 60), s = data.duration % 60;
                durationEl.textContent = `${m}:${s.toString().padStart(2, '0')}`;
            }

            formatSelect.innerHTML = '';
            data.formats.forEach(f => {
                const opt = document.createElement('option');
                opt.value = f.format_id;
                const size = f.filesize ? `(${(f.filesize / 1048576).toFixed(1)} MB)` : '';
                opt.textContent = `${f.label} ${size}`.trim();
                formatSelect.appendChild(opt);
            });

            if (!data.has_ffmpeg) qualityWarning?.classList.remove('hidden');
            showTranscriptBtn?.classList.remove('hidden');
            videoInfoCard?.classList.remove('hidden');
            videoInfoCard?.classList.add('fade-in');

        } catch (err) { showToast(`Error: ${err.message}`, 'error'); }
        finally { loadingSpinner?.classList.add('hidden'); }
    });

    // ─── DOWNLOAD ────────────────────────────────────────────────────────────────
    downloadBtn?.addEventListener('click', async () => {
        const url = videoUrlInput?.value.trim();
        const formatId = formatSelect?.value;
        const startTime = document.getElementById('clip-start')?.value.trim();
        const endTime = document.getElementById('clip-end')?.value.trim();

        downloadBtn.disabled = true;
        downloadProgress?.classList.remove('hidden');

        const downloadUid = Math.random().toString(36).substring(2, 15);
        const downloadInterval = setInterval(async () => {
            try {
                const r = await fetch(`${API_BASE}/progress/${downloadUid}`);
                if (r.ok) {
                    const data = await r.json();
                    updateProgress(data.progress || 0, data.text || 'Procesando en el servidor...');
                }
            } catch (e) {}
        }, 800);

        try {
            const bodyData = { url, format_id: formatId, uid: downloadUid };
            if (startTime) bodyData.start_time = startTime;
            if (endTime) bodyData.end_time = endTime;

            const r = await fetch(`${API_BASE}/download`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bodyData) });
            if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Error en descarga'); }
            clearInterval(interval);
            updateProgress(95, 'Preparando archivo...');
            const blob = await r.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            
            let filename = `${titleEl.textContent.substring(0, 40).trim() || 'video'}`;
            
            const selectedText = formatSelect?.options[formatSelect?.selectedIndex]?.text || '';
            const qualityMatch = selectedText.split(' ')[0];
            if (qualityMatch && qualityMatch !== 'Mejor') {
                filename += `_${qualityMatch}`;
            }
            
            if (startTime) filename += `_desde_${startTime.replace(/:/g, '-')}`;
            
            // Intentar leer el nombre del archivo desde el header Content-Disposition del servidor
            const disposition = r.headers.get('Content-Disposition') || '';
            const cdMatch = disposition.match(/filename\*?=(?:utf-8'')?([^;\n]+)/i);
            if (cdMatch) {
                // Usar el nombre de archivo que mandó el servidor (ya tiene la extensión correcta)
                const serverFilename = decodeURIComponent(cdMatch[1].replace(/["']/g, '').trim());
                // Extraer solo la extensión del servidor
                const serverExt = serverFilename.split('.').pop();
                a.download = `${filename}.${serverExt}`;
            } else {
                // Fallback: determinar extensión por formato seleccionado
                const isMP3 = formatId === 'mp3' || selectedText.toLowerCase().includes('mp3');
                a.download = `${filename}.${isMP3 ? 'mp3' : 'mp4'}`;
            }
            
            document.body.appendChild(a); a.click();
            URL.revokeObjectURL(a.href); a.remove();
            updateProgress(100, 'Descarga completada!');
            setTimeout(() => downloadProgress?.classList.add('hidden'), 4000);
        } catch (err) {
            clearInterval(downloadInterval);
            showToast(`Error: ${err.message}`, 'error');
            downloadProgress?.classList.add('hidden');
        } finally { 
            clearInterval(downloadInterval);
            downloadBtn.disabled = false; 
        }
    });

    // ─── TRANSCRIPT FROM URL ─────────────────────────────────────────────────────
    let selectedTargetLang = 'es';
    const langBtns = document.querySelectorAll('.lang-btn');
    langBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            langBtns.forEach(b => {
                b.classList.remove('active', 'border-primary/40', 'bg-primary/10', 'text-primary');
                b.classList.add('border-white/10', 'bg-white/5', 'text-slate-400');
            });
            const target = e.currentTarget;
            target.classList.add('active', 'border-primary/40', 'bg-primary/10', 'text-primary');
            target.classList.remove('border-white/10', 'bg-white/5', 'text-slate-400');
            selectedTargetLang = target.dataset.lang;
        });
    });

    window.downloadErrorLog = async (sessionUid) => {
        try {
            const r = await fetch(`${API_BASE}/logs/${sessionUid}`);
            const d = await r.json();
            const blob = new Blob([d.logs], { type: 'text/plain' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `reporte_error_${sessionUid}.txt`;
            a.click();
        } catch (e) {
            console.error(e);
            alert("No se pudo descargar el log.");
        }
    };


    showTranscriptBtn?.addEventListener('click', async () => {
        // Evitar doble ejecución simultánea
        if (isTranscribing) return;
        isTranscribing = true;

        // Cancelar poll anterior si existe
        if (activeTranscriptPollInterval) {
            clearInterval(activeTranscriptPollInterval);
            activeTranscriptPollInterval = null;
        }
        // Cancelar fetch anterior si existe
        if (activeAbortController) activeAbortController.abort();
        activeAbortController = new AbortController();
        const transcriptAbort = activeAbortController;

        const url = videoUrlInput?.value.trim();
        transcriptSection?.classList.remove('hidden');
        transcriptSection?.classList.add('fade-in');
        transcriptContent.innerHTML = `
            <div class="space-y-3">
                <div class="flex items-center gap-3 text-slate-400">
                    <div class="w-5 h-5 border-2 border-slate-700 border-t-accent rounded-full animate-spin flex-shrink-0"></div>
                    <p id="transcript-progress-text" class="text-sm animate-pulse">Iniciando proceso...</p>
                    <span id="transcript-progress-pct" class="text-xs text-accent font-mono ml-auto">0%</span>
                </div>
                <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                    <div id="transcript-progress-bar" class="h-full bg-gradient-to-r from-accent to-primary rounded-full transition-all duration-500" style="width:0%"></div>
                </div>
            </div>`;
        showTranscriptBtn.disabled = true;

        const transcriptUid = Math.random().toString(36).substring(2, 15);
        activeTranscriptPollInterval = setInterval(async () => {
            try {
                const r = await fetch(`${API_BASE}/progress/${transcriptUid}`);
                if (r.ok) {
                    const data = await r.json();
                    const textEl = document.getElementById('transcript-progress-text');
                    const pctEl  = document.getElementById('transcript-progress-pct');
                    const barEl  = document.getElementById('transcript-progress-bar');
                    if (textEl && data.text) textEl.textContent = data.text;
                    if (pctEl) pctEl.textContent = `${data.progress || 0}%`;
                    if (barEl) barEl.style.width = `${data.progress || 0}%`;
                }
            } catch (e) {}
        }, 800);

        try {
            const reqBody = { url, groq_api_key: localStorage.getItem(GROQ_KEY_STORE) || undefined, uid: transcriptUid };
            const r = await fetch(`${API_BASE}/transcript`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody),
                signal: transcriptAbort.signal
            });
            const data = await r.json();

            clearInterval(activeTranscriptPollInterval);
            activeTranscriptPollInterval = null;

            if (data.error) {
                    const errorMsg = escapeHtml(data.error.replace(/\u001b\[[0-9;]*m/g, ''));
                    transcriptContent.innerHTML = `
                        <div class="bg-red-500/10 p-6 rounded-2xl border border-red-500/20 text-red-400 text-sm space-y-4">
                            <div class="flex items-center gap-2">
                                <span class="material-symbols-outlined">error</span>
                                <p class="font-bold">Error en la transcripción</p>
                            </div>
                            <p class="opacity-80">${errorMsg}</p>
                            <div class="pt-2">
                                <p class="text-[10px] text-slate-500 mb-3 italic">Si el error persiste, descarga el reporte y envíaselo al administrador.</p>
                                <button onclick="downloadErrorLog('${escapeHtml(transcriptUid)}')" class="bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2">
                                    <span class="material-symbols-outlined text-sm">bug_report</span> Descargar Reporte de Error
                                </button>
                            </div>
                        </div>`;
                    return;
            }


            currentTranscript = data.transcript;
            renderTranscript(data.transcript, data.method, data.srt, data.segments);
            downloadTxtBtn?.classList.remove('hidden');

            saveToHistory({ url, platform: detectPlatformFromUrl(url), title: titleEl.textContent || url, transcript: data.transcript, srt: data.srt, segments: data.segments });

        } catch (err) {
            clearInterval(activeTranscriptPollInterval);
            activeTranscriptPollInterval = null;
            if (err.name === 'AbortError') return; // cancelado intencionalmente
            transcriptContent.innerHTML = `<p class="text-red-400 text-sm">Error al conectar con el servidor.</p>`;
        } finally { 
            clearInterval(activeTranscriptPollInterval);
            activeTranscriptPollInterval = null;
            isTranscribing = false;
            showTranscriptBtn.disabled = false; 
        }
    });

    downloadSrtBtn?.addEventListener('click', () => {
        if (!currentSrt) return;
        const title = (titleEl?.textContent || 'Subtitulos').trim().substring(0, 60);
        const safeTitle = title.replace(/[/\\?%*:|"<>]/g, '-');
        const blob = new Blob([currentSrt], { type: 'text/srt;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${safeTitle}.srt`;
        a.click();
        URL.revokeObjectURL(a.href);
    });

    function formatTimestamp(sec) {
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    function formatHHMMSS(sec) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = Math.floor(sec % 60);
        const mm = m.toString().padStart(2, '0');
        const ss = s.toString().padStart(2, '0');
        if (h > 0) {
            return `${h.toString().padStart(2, '0')}:${mm}:${ss}`;
        }
        return `${mm}:${ss}`;
    }

    function deduplicateSegments(segs) {
        if (!segs || segs.length === 0) return [];
        const result = [];
        let prevText = "";
        for (const seg of segs) {
            const cleanText = seg.text.trim();
            if (!cleanText) continue;
            // Only skip if the segment is an EXACT duplicate of the previous one
            if (prevText && cleanText === prevText) continue;
            // Skip only if it's a very short substring already contained in the previous (rolling subs artifact)
            if (prevText && cleanText.length < 25 && prevText.includes(cleanText)) continue;
            result.push(seg);
            prevText = cleanText;
        }
        return result;
    }

    function renderTranscript(text, method, srt = '', segments = []) {
        currentSrt = srt || '';
        currentSegments = segments || [];
        if (currentSrt) {
            downloadSrtBtn?.classList.remove('hidden');
        } else {
            downloadSrtBtn?.classList.add('hidden');
        }
        const methodLabels = { 
            subtitles: 'Subtítulos directos', 
            groq_whisper_v3: 'IA Whisper v3 (Groq)', 
            groq_whisper_v3_file: 'IA Whisper v3 - Archivo', 
            local_whisper: 'IA Whisper Local', 
            cache: 'Caché local' 
        };
        
        // 1. Inyectar herramientas ARRIBA (antes del texto)
        const toolsContainer = document.getElementById('journalist-tools-wrapper');
        if (toolsContainer) {
            toolsContainer.innerHTML = buildJournalistToolsHtml('vc');
            toolsContainer.classList.remove('hidden');
        }

        // 2. Mostrar la sección de transcripción si está oculta
        transcriptSection?.classList.remove('hidden');

        // 3. Crear cabecera con etiqueta de método y selectores de vista
        const methodLabel = methodLabels[method] || method;
        const showSelector = currentSegments && currentSegments.length > 0;
        
        transcriptContent.innerHTML = `
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 border-b border-white/5 pb-4 shrink-0">
                <div class="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest bg-white/5 py-1.5 px-3 rounded-full w-fit">
                    <span class="material-symbols-outlined text-xs">auto_awesome</span>
                    ${methodLabel}
                </div>
                ${showSelector ? `
                <div class="flex bg-slate-950/60 p-1 rounded-xl border border-white/5 w-fit">
                    <button id="view-mode-clean" class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 bg-primary text-white">
                        <span class="material-symbols-outlined text-sm">notes</span> Texto Limpio
                    </button>
                    <button id="view-mode-interactive" class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 text-slate-400 hover:text-slate-200">
                        <span class="material-symbols-outlined text-sm">content_cut</span> Recortar por Texto
                    </button>
                </div>
                ` : ''}
            </div>
            <div id="transcript-text-container" class="text-slate-300 text-sm leading-relaxed">
                ${formatAIResponse(text)}
            </div>`;

        // Añadir manejadores de evento para el selector de vistas
        if (showSelector) {
            const btnClean = document.getElementById('view-mode-clean');
            const btnInteractive = document.getElementById('view-mode-interactive');
            const textContainer = document.getElementById('transcript-text-container');

            // Inject inline clip tool inside transcript section (visible when in interactive mode)
            renderInlineClipTool();
            
            btnClean?.addEventListener('click', () => {
                btnClean.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 bg-primary text-white";
                btnInteractive.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 text-slate-400 hover:text-slate-200";
                textContainer.innerHTML = formatAIResponse(text);
                document.getElementById('inline-clip-tool')?.classList.add('hidden');
            });
            
            btnInteractive?.addEventListener('click', () => {
                btnInteractive.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 bg-primary text-white";
                btnClean.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 text-slate-400 hover:text-slate-200";
                
                // Deduplicar segmentos antes de renderizar
                const cleanSegs = deduplicateSegments(currentSegments);
                textContainer.innerHTML = `<div class="segment-list">${cleanSegs.map(seg => {
                    const timeLabel = formatTimestamp(seg.start);
                    const timeEnd   = formatTimestamp(seg.end);
                    return `<div class="interactive-segment" data-start="${seg.start}" data-end="${seg.end}" title="Click: fijar inicio/fin del recorte">
                        <span class="interactive-segment-time">${timeLabel}</span>
                        <span class="interactive-segment-text">${seg.text}</span>
                    </div>`;
                }).join('')}</div>`;

                // Show inline clip tool
                document.getElementById('inline-clip-tool')?.classList.remove('hidden');
            });
        }

        // 4. Mostrar sección de chat
        document.getElementById('ai-chat-section')?.classList.remove('hidden');
        // Limpiar historial de chat al cargar nueva transcripción
        const chatHistory = document.getElementById('chat-history');
        if (chatHistory) chatHistory.innerHTML = '';
    }

    /** Injects (or updates) the inline clip tool inside the transcript section */
    function renderInlineClipTool() {
        if (document.getElementById('inline-clip-tool')) return; // already exists
        const clipHtml = `
        <div id="inline-clip-tool" class="hidden mt-3 p-4 rounded-2xl border border-primary/20 bg-primary/5 space-y-3 shrink-0">
            <div class="flex items-center gap-2 text-[10px] font-bold text-primary uppercase tracking-widest">
                <span class="material-symbols-outlined text-sm">content_cut</span>
                Selector de Recorte — haz clic en una frase para fijar los tiempos
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div class="relative">
                    <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[11px] font-bold">Desde:</span>
                    <input type="text" id="inline-clip-start" placeholder="00:00" autocomplete="off"
                        class="w-full bg-slate-900/60 border border-white/10 rounded-xl py-2.5 pl-14 pr-3 text-sm text-slate-200 focus:ring-2 focus:ring-primary outline-none font-mono">
                </div>
                <div class="relative">
                    <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[11px] font-bold">Hasta:</span>
                    <input type="text" id="inline-clip-end" placeholder="00:00" autocomplete="off"
                        class="w-full bg-slate-900/60 border border-white/10 rounded-xl py-2.5 pl-14 pr-3 text-sm text-slate-200 focus:ring-2 focus:ring-primary outline-none font-mono">
                </div>
            </div>
            <div class="flex gap-2">
                <button id="inline-clip-apply-btn" class="flex-1 bg-primary hover:bg-primary/80 text-white font-bold py-2.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-base">content_cut</span> Aplicar al descargador
                </button>
                <button id="inline-clip-clear-btn" class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 font-bold py-2.5 px-4 rounded-xl text-sm transition-all">
                    Limpiar
                </button>
            </div>
        </div>`;
        // Inject after the transcript-content div, before the ai-chat-section
        const aiChatSection = document.getElementById('ai-chat-section');
        if (aiChatSection) {
            aiChatSection.insertAdjacentHTML('beforebegin', clipHtml);
        } else {
            transcriptSection?.insertAdjacentHTML('beforeend', clipHtml);
        }

        // Wire buttons
        document.getElementById('inline-clip-apply-btn')?.addEventListener('click', () => {
            const startVal = document.getElementById('inline-clip-start')?.value.trim();
            const endVal = document.getElementById('inline-clip-end')?.value.trim();
            const clipStart = document.getElementById('clip-start');
            const clipEnd = document.getElementById('clip-end');
            if (clipStart && startVal) clipStart.value = startVal;
            if (clipEnd && endVal) clipEnd.value = endVal;
            if (startVal || endVal) {
                showToast(`Recorte fijado: ${startVal || '—'} → ${endVal || '—'}`, 'success');
            } else {
                showToast('Primero hacé clic en segmentos para fijar tiempos', 'info');
            }
        });
        document.getElementById('inline-clip-clear-btn')?.addEventListener('click', () => {
            const si = document.getElementById('inline-clip-start');
            const ei = document.getElementById('inline-clip-end');
            if (si) si.value = '';
            if (ei) ei.value = '';
            const clipStart = document.getElementById('clip-start');
            const clipEnd = document.getElementById('clip-end');
            if (clipStart) clipStart.value = '';
            if (clipEnd) clipEnd.value = '';
            showToast('Recorte limpiado', 'info');
        });
    }

    // Segment actions menu listener
    transcriptContent?.addEventListener('click', (e) => {
        const segmentEl = e.target.closest('.interactive-segment');
        if (!segmentEl) return;
        
        const start = parseFloat(segmentEl.dataset.start);
        const end = parseFloat(segmentEl.dataset.end);
        
        // Remove existing menus
        document.querySelectorAll('.segment-actions-menu').forEach(el => el.remove());
        
        // Create menu
        const menu = document.createElement('div');
        menu.className = 'segment-actions-menu';
        
        const startBtn = document.createElement('button');
        startBtn.innerHTML = '<span class="material-symbols-outlined text-[14px]">play_arrow</span> Iniciar corte';
        startBtn.onclick = () => {
            const formattedStart = formatHHMMSS(start);
            // Fill old clip input (YouTube tab)
            const startInput = document.getElementById('clip-start');
            if (startInput) { startInput.value = formattedStart; startInput.dispatchEvent(new Event('input')); }
            // Fill inline clip input (Transcript panel)
            const inlineStartInput = document.getElementById('inline-clip-start');
            if (inlineStartInput) inlineStartInput.value = formattedStart;
            // Visual highlight on this segment
            document.querySelectorAll('.interactive-segment.selected-start').forEach(el => el.classList.remove('selected-start'));
            segmentEl.classList.add('selected-start');
            menu.remove();
            showToast('Inicio fijado: ' + formattedStart, 'success');
        };
        
        const endBtn = document.createElement('button');
        endBtn.innerHTML = '<span class="material-symbols-outlined text-[14px]">stop</span> Finalizar corte';
        endBtn.onclick = () => {
            const formattedEnd = formatHHMMSS(end);
            // Fill old clip input (YouTube tab)
            const endInput = document.getElementById('clip-end');
            if (endInput) { endInput.value = formattedEnd; endInput.dispatchEvent(new Event('input')); }
            // Fill inline clip input (Transcript panel)
            const inlineEndInput = document.getElementById('inline-clip-end');
            if (inlineEndInput) inlineEndInput.value = formattedEnd;
            // Visual highlight on this segment
            document.querySelectorAll('.interactive-segment.selected-end').forEach(el => el.classList.remove('selected-end'));
            segmentEl.classList.add('selected-end');
            menu.remove();
            showToast('Fin fijado: ' + formattedEnd, 'success');
        };
        
        const copyBtn = document.createElement('button');
        copyBtn.innerHTML = '<span class="material-symbols-outlined text-[14px]">content_copy</span> Copiar frase';
        copyBtn.onclick = () => {
            // Get the text from the dedicated text span, not the whole element (which includes the timestamp)
            const textSpan = segmentEl.querySelector('.interactive-segment-text');
            const cleanText = textSpan ? textSpan.textContent.trim() : segmentEl.textContent.replace(/^\d{1,2}:\d{2}\s*/, '').trim();
            navigator.clipboard.writeText(cleanText);
            menu.remove();
            showToast('Frase copiada', 'success');
        };
        
        menu.appendChild(startBtn);
        menu.appendChild(endBtn);
        menu.appendChild(copyBtn);
        
        // Position menu near the segment element
        document.body.appendChild(menu);
        const rect = segmentEl.getBoundingClientRect();
        menu.style.left = `${rect.left + window.scrollX}px`;
        menu.style.top = `${rect.bottom + window.scrollY + 5}px`;
        
        // Close menu when clicking outside
        setTimeout(() => {
            const closeMenu = (event) => {
                if (!menu.contains(event.target)) {
                    menu.remove();
                    document.removeEventListener('click', closeMenu);
                }
            };
            document.addEventListener('click', closeMenu);
        }, 100);
    });

    // ─── WHATSAPP FILE UPLOAD ────────────────────────────────────────────────────
    const waFileInput = document.getElementById('wa-file-input');
    const waDropZone  = document.getElementById('wa-dropzone');
    const waResult    = document.getElementById('wa-result');

    document.getElementById('wa-upload-btn')?.addEventListener('click', () => waFileInput?.click());
    waFileInput?.addEventListener('change', () => { if (waFileInput.files[0]) processAudioFile(waFileInput.files[0]); });

    waDropZone?.addEventListener('dragover', e => { e.preventDefault(); waDropZone.classList.add('border-primary', 'scale-[1.01]'); });
    waDropZone?.addEventListener('dragleave', () => waDropZone.classList.remove('border-primary', 'scale-[1.01]'));
    waDropZone?.addEventListener('drop', e => {
        e.preventDefault(); waDropZone.classList.remove('border-primary', 'scale-[1.01]');
        const file = e.dataTransfer.files[0]; if (file) processAudioFile(file);
    });

    async function processAudioFile(file) {
        const ALLOWED = ['.ogg','.opus','.mp3','.m4a','.wav','.mp4','.aac','.webm','.weba'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!ALLOWED.includes(ext)) { showToast(`Formato no soportado: ${ext}`, 'error'); return; }

        if (waDropZone) waDropZone.innerHTML = `
            <div class="flex flex-col items-center gap-3">
                <div class="w-10 h-10 border-4 border-slate-700 border-t-primary rounded-full animate-spin"></div>
                <p class="font-semibold text-white text-sm">${file.name}</p>
                <p class="text-slate-400 text-xs animate-pulse">Transcribiendo con IA Whisper...</p>
            </div>`;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('target_lang', selectedTargetLang);
        formData.append('uid', uid);
        formData.append('groq_api_key', localStorage.getItem(GROQ_KEY_STORE) || '');


        try {
            const r    = await fetch(`${API_BASE}/transcript-file`, { method: 'POST', body: formData });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en la transcripcion');

            currentTranscript = data.transcript;
            currentSrt = data.srt || '';
            
            // Usar la columna derecha (como YouTube)
            renderTranscript(data.transcript, 'groq_whisper_v3_file', data.srt, data.segments);
            downloadTxtBtn?.classList.remove('hidden');

            saveToHistory({ url: `whatsapp:${file.name}`, platform: 'whatsapp', title: file.name, transcript: data.transcript, srt: data.srt, segments: data.segments });

            if (waDropZone) waDropZone.innerHTML = `
                <div class="flex flex-col items-center gap-2">
                    <span class="material-symbols-outlined text-emerald-400 text-4xl mb-1">check_circle</span>
                    <p class="font-bold text-white text-sm">¡Audio listo!</p>
                    <p class="text-slate-500 text-xs">${file.name}</p>
                    <button onclick="document.getElementById('wa-file-input').click()" class="mt-2 text-[10px] font-bold text-primary uppercase border border-primary/20 px-3 py-1 rounded-full hover:bg-primary/10 transition-all">Subir otro</button>
                </div>`;

            if (waDropZone) waDropZone.innerHTML = `
                <span class="material-symbols-outlined text-primary text-4xl mb-3">mic</span>
                <p class="font-semibold text-white">Subir otro audio</p>
                <p class="text-slate-500 text-xs mt-1">.ogg · .mp3 · .m4a · .wav</p>`;

        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
            if (waDropZone) waDropZone.innerHTML = `
                <span class="material-symbols-outlined text-red-400 text-4xl mb-2">error</span>
                <p class="text-red-300 text-sm font-semibold">Error al procesar</p>
                <p class="text-slate-500 text-xs">${err.message}</p>`;
        }
    }

    window._wa = {
        copy:     ()      => { if (currentTranscript) { navigator.clipboard.writeText(currentTranscript); showToast('Copiado', 'success'); } },
        download: (name) => {
            if (!currentTranscript) return;
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([currentTranscript], { type: 'text/plain' }));
            a.download = name.replace(/\.[^.]+$/, '') + '_transcripcion.txt';
            a.click();
        }
    };

    // ─── VIDEO LOCAL UPLOAD ──────────────────────────────────────────────────────
    const vidFileInput = document.getElementById('vid-file-input');
    const vidDropZone  = document.getElementById('vid-dropzone');
    const vidResult    = document.getElementById('vid-result');
    const vidProgress  = document.getElementById('vid-progress');
    const vidProgBar   = document.getElementById('vid-progress-bar');
    const vidProgText  = document.getElementById('vid-progress-text');

    document.getElementById('vid-upload-btn')?.addEventListener('click', () => vidFileInput?.click());
    vidFileInput?.addEventListener('change', () => { if (vidFileInput.files[0]) processVideoFile(vidFileInput.files[0]); });

    vidDropZone?.addEventListener('dragover', e => { e.preventDefault(); vidDropZone.classList.add('border-emerald-400', 'scale-[1.01]'); });
    vidDropZone?.addEventListener('dragleave', () => vidDropZone.classList.remove('border-emerald-400', 'scale-[1.01]'));
    vidDropZone?.addEventListener('drop', e => {
        e.preventDefault(); vidDropZone.classList.remove('border-emerald-400', 'scale-[1.01]');
        const file = e.dataTransfer.files[0]; if (file) processVideoFile(file);
    });

    async function processVideoFile(file) {
        const ALLOWED = ['.mp4', '.mov', '.avi', '.mkv', '.webm'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!ALLOWED.includes(ext)) { showToast(`Formato de video no soportado: ${ext}`, 'error'); return; }

        // UI Reset
        vidProgress?.classList.remove('hidden');
        vidResult?.classList.add('hidden');
        vidProgBar.style.width = '0%';
        vidProgText.textContent = 'Subiendo video...';

        const formData = new FormData();
        formData.append('file', file);
        formData.append('target_lang', selectedTargetLang);
        formData.append('uid', uid);
        formData.append('groq_api_key', localStorage.getItem(GROQ_KEY_STORE) || '');
        formData.append('is_local_video', 'true');

        try {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${API_BASE}/transcript-file`, true);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    vidProgBar.style.width = `${pct}%`;
                    if (pct < 100) vidProgText.textContent = `Cargando video: ${pct}%`;
                    else vidProgText.textContent = 'Procesando en el servidor...';
                }
            };

            const response = await new Promise((resolve, reject) => {
                xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText));
                xhr.onerror = () => reject(new Error('Fallo de red'));
                xhr.send(formData);
            });

            currentTranscript = response.transcript;
            currentSrt = response.srt || '';

            // Usar la columna derecha (como YouTube)
            renderTranscript(response.transcript, 'groq_whisper_v3_file', response.srt, response.segments);
            downloadTxtBtn?.classList.remove('hidden');

            saveToHistory({ url: `video:${file.name}`, platform: 'video', title: file.name, transcript: response.transcript, srt: response.srt, segments: response.segments });
            
            vidProgress?.classList.add('hidden');
            if (vidDropZone) vidDropZone.innerHTML = `
                <div class="flex flex-col items-center gap-2">
                    <span class="material-symbols-outlined text-emerald-400 text-4xl mb-1">check_circle</span>
                    <p class="font-bold text-white text-sm">¡Video listo!</p>
                    <p class="text-slate-500 text-xs">${file.name}</p>
                    <button onclick="document.getElementById('vid-file-input').click()" class="mt-2 text-[10px] font-bold text-primary uppercase border border-primary/20 px-3 py-1 rounded-full hover:bg-primary/10 transition-all">Subir otro</button>
                </div>`;

        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
            vidProgText.textContent = 'Fallo al procesar el video';
            vidProgBar.classList.add('bg-red-500');
        }
    }

    window._vid = {
        copy:     ()      => { if (currentTranscript) { navigator.clipboard.writeText(currentTranscript); showToast('Copiado', 'success'); } },
        download: (name) => {
            if (!currentTranscript) return;
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([currentTranscript], { type: 'text/plain' }));
            a.download = name.replace(/\.[^.]+$/, '') + '_transcripcion.txt';
            a.click();
        }
    };

    // ─── JOURNALIST TOOLS ────────────────────────────────────────────────────────
    function buildJournalistToolsHtml(prefix) {
        return `
        <div id="${prefix}-tools-container">
            <div class="flex items-center gap-2 mb-4">
                <span class="bg-primary/20 text-primary p-1.5 rounded-lg flex items-center"><span class="material-symbols-outlined text-sm">newspaper</span></span>
                <h5 class="font-bold text-white text-sm">Herramientas periodísticas</h5>
                <span class="ml-auto text-[10px] font-bold text-slate-600 uppercase tracking-widest">IA</span>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4">
                <button data-tool="summary" data-prefix="${prefix}" class="j-tool-btn group bg-primary/10 hover:bg-primary/25 border border-primary/20 hover:border-primary/40 py-3.5 px-3 rounded-xl text-slate-200 text-sm font-bold flex flex-col items-center gap-1.5 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-xl text-primary group-hover:scale-110 transition-transform">summarize</span>
                    <span>Resumen</span>
                </button>
                <button data-tool="quotes" data-prefix="${prefix}" class="j-tool-btn group bg-accent/10 hover:bg-accent/20 border border-accent/20 hover:border-accent/40 py-3.5 px-3 rounded-xl text-slate-200 text-sm font-bold flex flex-col items-center gap-1.5 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-xl text-accent group-hover:scale-110 transition-transform">format_quote</span>
                    <span>Citas</span>
                </button>
                <button data-tool="data" data-prefix="${prefix}" class="j-tool-btn group bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 hover:border-orange-500/40 py-3.5 px-3 rounded-xl text-slate-200 text-sm font-bold flex flex-col items-center gap-1.5 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-xl text-orange-400 group-hover:scale-110 transition-transform">data_object</span>
                    <span>Datos duros</span>
                </button>
                <button data-tool="angle" data-prefix="${prefix}" class="j-tool-btn group bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 hover:border-emerald-500/40 py-3.5 px-3 rounded-xl text-slate-200 text-sm font-bold flex flex-col items-center gap-1.5 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-xl text-emerald-400 group-hover:scale-110 transition-transform">lightbulb</span>
                    <span>Ángulos</span>
                </button>
                <button data-tool="diarization" data-prefix="${prefix}" class="j-tool-btn group bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 hover:border-purple-500/40 py-3.5 px-3 rounded-xl text-slate-200 text-sm font-bold flex flex-col items-center gap-1.5 transition-all active:scale-95">
                    <span class="material-symbols-outlined text-xl text-purple-400 group-hover:scale-110 transition-transform">group</span>
                    <span>Hablantes</span>
                </button>
            </div>
            <div id="${prefix}-ai-output" class="hidden mt-2 bg-black/30 rounded-2xl p-5 border border-white/5 fade-in"></div>
        </div>`;
    }

    // Event delegation para botones de herramientas periodísticas (inyectados dinámicamente)
    document.body.addEventListener('click', async (e) => {
        const btn = e.target.closest('.j-tool-btn');
        if (!btn) return;

        const mode   = btn.dataset.tool;
        const prefix = btn.dataset.prefix;
        if (!mode || !prefix) return;

        if (!currentTranscript || currentTranscript.length < 50) {
            showToast('Primero transcribí un audio o video', 'error'); return;
        }

        const outputEl = document.getElementById(`${prefix}-ai-output`);
        if (!outputEl) return;

        // ── Citas: endpoint especial con tiempos ──────────────────────────────
        if (mode === 'quotes') {
            await runQuotesWithTimes(outputEl, prefix);
            return;
        }

        // ── Resto de herramientas: flujo genérico ─────────────────────────────
        const cfg = {
            summary : { label: 'Resumen ejecutivo',  icon: 'summarize',    color: 'text-primary' },
            data    : { label: 'Datos duros',        icon: 'data_object',  color: 'text-orange-400' },
            angle   : { label: 'Ángulos de nota',    icon: 'lightbulb',    color: 'text-emerald-400' },
            diarization: { label: 'Identificación de hablantes', icon: 'group', color: 'text-purple-400' },
        }[mode];
        if (!cfg) return;

        outputEl.classList.remove('hidden');
        outputEl.innerHTML = `
            <div class="flex items-center gap-2 mb-3">
                <span class="material-symbols-outlined text-base ${cfg.color}">${cfg.icon}</span>
                <span class="font-bold text-white text-sm">${cfg.label}</span>
                <div class="ml-auto w-4 h-4 border-2 border-slate-700 border-t-accent rounded-full animate-spin"></div>
            </div>
            <p class="text-slate-500 text-xs animate-pulse">Analizando con IA...</p>`;

        try {
            const reqBody = { transcript: currentTranscript, mode, groq_api_key: localStorage.getItem(GROQ_KEY_STORE) || undefined };
            const r    = await fetch(`${API_BASE}/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reqBody) });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en el analisis');

            outputEl.innerHTML = `
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <span class="material-symbols-outlined text-base ${cfg.color}">${cfg.icon}</span>
                        <span class="font-bold text-white text-sm">${cfg.label}</span>
                    </div>
                    <button onclick="navigator.clipboard.writeText(this.closest('[id]').querySelector('.ai-result-text')?.textContent||''); this.textContent='Copiado'" class="text-[10px] font-bold uppercase tracking-widest bg-white/5 text-slate-400 px-2 py-1 rounded-full hover:bg-white/10 transition-all">
                        Copiar
                    </button>
                </div>
                <div class="ai-result-text text-slate-300 text-sm leading-relaxed">${formatAIResponse(data.result)}</div>`;

        } catch (err) {
            renderAnalyzeError(outputEl, err);
        }
    });

    /** Llama a /api/quotes y renderiza las cards con tiempos y botones de recorte */
    async function runQuotesWithTimes(outputEl, prefix) {
        outputEl.classList.remove('hidden');
        outputEl.innerHTML = `
            <div class="flex items-center gap-2 mb-3">
                <span class="material-symbols-outlined text-base text-accent">format_quote</span>
                <span class="font-bold text-white text-sm">Citas textuales</span>
                <div class="ml-auto w-4 h-4 border-2 border-slate-700 border-t-accent rounded-full animate-spin"></div>
            </div>
            <p class="text-slate-500 text-xs animate-pulse">Buscando las mejores citas con IA...</p>`;

        try {
            const reqBody = {
                transcript: currentTranscript,
                segments: currentSegments || [],
                groq_api_key: localStorage.getItem(GROQ_KEY_STORE) || undefined
            };
            const r    = await fetch(`${API_BASE}/quotes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reqBody) });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en citas');

            renderQuoteCards(outputEl, data.quotes || [], prefix);

        } catch (err) {
            renderAnalyzeError(outputEl, err);
        }
    }

    /** Renders quote cards inside outputEl */
    function renderQuoteCards(outputEl, quotes, prefix) {
        if (!quotes.length) {
            outputEl.innerHTML = `<p class="text-slate-500 text-xs">No se encontraron citas destacables.</p>`;
            return;
        }

        const cardsHtml = quotes.map((q, i) => {
            const hasTime = q.has_time && q.start != null;
            const startFmt = hasTime ? formatHHMMSS(q.start) : null;
            const endFmt   = hasTime ? formatHHMMSS(q.end)   : null;
            const timeBadge = hasTime
                ? `<div class="quote-time-badge">
                    <span class="material-symbols-outlined text-[13px]">schedule</span>
                    ${startFmt} → ${endFmt}
                   </div>`
                : `<div class="quote-time-badge quote-time-unknown">
                    <span class="material-symbols-outlined text-[13px]">schedule</span>
                    Tiempo no localizado
                   </div>`;

            const clipBtn = hasTime
                ? `<button class="quote-clip-btn" data-start="${q.start}" data-end="${q.end}" title="Fijar este recorte">
                    <span class="material-symbols-outlined text-[13px]">content_cut</span> Recortar
                   </button>`
                : '';

            return `
            <div class="quote-card">
                <div class="quote-index">Cita ${i + 1}</div>
                <blockquote class="quote-text">&ldquo;${q.quote}&rdquo;</blockquote>
                <p class="quote-note">${q.note}</p>
                <div class="quote-actions">
                    ${timeBadge}
                    <div class="quote-buttons">
                        ${clipBtn}
                        <button class="quote-copy-btn" data-quote="${q.quote.replace(/"/g, '&quot;')}">
                            <span class="material-symbols-outlined text-[13px]">content_copy</span> Copiar
                        </button>
                    </div>
                </div>
            </div>`;
        }).join('');

        outputEl.innerHTML = `
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <span class="material-symbols-outlined text-base text-accent">format_quote</span>
                    <span class="font-bold text-white text-sm">Citas textuales</span>
                    <span class="text-[10px] text-slate-500 font-bold bg-white/5 px-2 py-0.5 rounded-full">${quotes.length} citas</span>
                </div>
                <button class="quotes-refresh-btn" title="Generar nuevas citas">
                    <span class="material-symbols-outlined text-[15px]">refresh</span> Nuevas citas
                </button>
            </div>
            <div class="quote-cards-list">${cardsHtml}</div>`;

        // Wire refresh button
        outputEl.querySelector('.quotes-refresh-btn')?.addEventListener('click', () => {
            runQuotesWithTimes(outputEl, prefix);
        });

        // Wire clip buttons
        outputEl.querySelectorAll('.quote-clip-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const start = parseFloat(btn.dataset.start);
                const end   = parseFloat(btn.dataset.end);
                const startFmt = formatHHMMSS(start);
                const endFmt   = formatHHMMSS(end);
                // Fill both clip inputs
                const cs = document.getElementById('clip-start');
                const ce = document.getElementById('clip-end');
                if (cs) cs.value = startFmt;
                if (ce) ce.value = endFmt;
                const ics = document.getElementById('inline-clip-start');
                const ice = document.getElementById('inline-clip-end');
                if (ics) ics.value = startFmt;
                if (ice) ice.value = endFmt;
                // Show inline clip tool if hidden
                document.getElementById('inline-clip-tool')?.classList.remove('hidden');
                showToast(`Recorte fijado: ${startFmt} → ${endFmt}`, 'success');
                // Visual feedback on the button
                btn.innerHTML = '<span class="material-symbols-outlined text-[13px]">check</span> Fijado';
                btn.classList.add('opacity-70');
                setTimeout(() => { btn.innerHTML = '<span class="material-symbols-outlined text-[13px]">content_cut</span> Recortar'; btn.classList.remove('opacity-70'); }, 2500);
            });
        });

        // Wire copy buttons
        outputEl.querySelectorAll('.quote-copy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                navigator.clipboard.writeText(btn.dataset.quote || '');
                btn.innerHTML = '<span class="material-symbols-outlined text-[13px]">check</span> Copiada';
                setTimeout(() => { btn.innerHTML = '<span class="material-symbols-outlined text-[13px]">content_copy</span> Copiar'; }, 2000);
            });
        });
    }

    function renderAnalyzeError(outputEl, err) {
        const isRateLimit = err.message.includes('429') || err.message.includes('Límite') || err.message.includes('rate_limit');
        outputEl.innerHTML = isRateLimit
            ? `<div class="flex flex-col gap-3">
                <div class="flex items-start gap-3">
                    <span class="material-symbols-outlined text-amber-400 text-xl flex-shrink-0">warning</span>
                    <div>
                        <p class="font-bold text-amber-300 text-sm mb-1">Límite de Groq alcanzado</p>
                        <p class="text-slate-400 text-xs leading-relaxed">Alcanzaste el límite de tokens gratuitos por hoy. Podés:</p>
                    </div>
                </div>
                <ul class="text-xs text-slate-400 space-y-1 pl-4">
                    <li>• Esperá unos minutos e intentá de nuevo</li>
                    <li>• Configurá tu propia API key en <strong class="text-primary cursor-pointer" onclick="document.querySelector('[data-tab=history]')?.click()">Configuración →</strong></li>
                </ul>
               </div>`
            : `<div class="flex items-start gap-2">
                <span class="material-symbols-outlined text-red-400 text-base flex-shrink-0">error</span>
                <p class="text-red-400 text-xs">${err.message}</p>
              </div>`;
    }

    // ─── COPY / DOWNLOAD (card de video) ────────────────────────────────────────

    /**
     * Devuelve la transcripción con el mismo formato de párrafos que se ve en
     * pantalla pero en texto plano (\n\n entre párrafos), listo para copiar o .txt
     */
    function getFormattedPlainText() {
        if (!currentTranscript) return '';
        const t = currentTranscript.trim();
        // Si ya tiene párrafos explícitos, respetar
        if (t.includes('\n\n')) return t;
        // Saltos simples → párrafos
        if (t.includes('\n')) {
            return t.split('\n').map(l => l.trim()).filter(l => l).join('\n\n');
        }
        // Intentar dividir por oraciones
        const sentences = t.match(/[^.!?]+[.!?]+["']?\s*/g);
        if (sentences && sentences.length > 3) {
            const out = [];
            for (let i = 0; i < sentences.length; i += 4) {
                const chunk = sentences.slice(i, i + 4).join('').trim();
                if (chunk) out.push(chunk);
            }
            return out.join('\n\n');
        }
        // Último recurso: párrafos de 70 palabras
        const words = t.split(/\s+/).filter(w => w);
        if (words.length > 70) {
            const out = [];
            for (let i = 0; i < words.length; i += 70) {
                const chunk = words.slice(i, i + 70).join(' ').trim();
                if (chunk) out.push(chunk);
            }
            return out.join('\n\n');
        }
        return t;
    }

    copyTranscriptBtn?.addEventListener('click', () => {
        if (!currentTranscript) return;
        navigator.clipboard.writeText(getFormattedPlainText());
        const orig = copyTranscriptBtn.innerHTML;
        copyTranscriptBtn.innerHTML = '<span class="material-symbols-outlined text-sm">check</span> COPIADO';
        setTimeout(() => { copyTranscriptBtn.innerHTML = orig; }, 2000);
    });

    downloadTxtBtn?.addEventListener('click', async () => {
        if (!currentTranscript) return;

        const title     = (titleEl?.textContent || 'Transcripcion').trim().substring(0, 60);
        const safeTitle = title.replace(/[/\\?%*:|"<>]/g, '-');
        const header    = `${title}\n${'─'.repeat(Math.min(title.length, 60))}\n\n`;
        const content   = header + getFormattedPlainText();

        // Feedback visual
        const origHtml = downloadTxtBtn.innerHTML;
        downloadTxtBtn.innerHTML = '<span class="material-symbols-outlined text-lg animate-spin">progress_activity</span> Generando...';
        downloadTxtBtn.disabled = true;

        try {
            if (typeof JSZip === 'undefined') throw new Error('JSZip no cargó');

            const zip  = new JSZip();
            zip.file(`${safeTitle}.txt`, content, { binary: false });

            const blob = await zip.generateAsync({
                type: 'blob',
                compression: 'DEFLATE',
                compressionOptions: { level: 6 }
            });

            const a = document.createElement('a');
            a.href     = URL.createObjectURL(blob);
            a.download = `${safeTitle}.zip`;
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 10000);

            downloadTxtBtn.innerHTML = '<span class="material-symbols-outlined text-lg">check</span> Descargado';
            setTimeout(() => { downloadTxtBtn.innerHTML = origHtml; downloadTxtBtn.disabled = false; }, 2500);

        } catch (err) {
            // Fallback a .txt si JSZip falla
            console.warn('JSZip no disponible, descargando .txt:', err);
            const a = document.createElement('a');
            a.href     = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
            a.download = `${safeTitle}.txt`;
            a.click();
            downloadTxtBtn.innerHTML = origHtml;
            downloadTxtBtn.disabled  = false;
        }
    });



    downloadThumbBtn?.addEventListener('click', () => { if (currentMaxResThumbnail) window.open(currentMaxResThumbnail, '_blank'); });

    // ─── PROGRESS ────────────────────────────────────────────────────────────────
    function updateProgress(val, text) {
        if (progressFill)       progressFill.style.width      = `${val}%`;
        if (progressPercentage) progressPercentage.textContent = `${val}%`;
        if (text && progressText) progressText.textContent    = text;
    }

    // ─── TOAST ───────────────────────────────────────────────────────────────────
    function showToast(message, type = 'info') {
        const colors = { error: 'bg-red-500/90', success: 'bg-emerald-600/90', info: 'bg-slate-700/90' };
        const icons  = { error: 'error', success: 'check_circle', info: 'info' };
        const toast  = document.createElement('div');
        toast.className = `fixed top-6 left-1/2 -translate-x-1/2 z-[200] flex items-center gap-3 px-5 py-3 rounded-2xl text-white text-sm font-semibold shadow-2xl ${colors[type]} fade-in`;
        toast.innerHTML = `<span class="material-symbols-outlined text-lg">${icons[type]}</span>${message}`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, 3500);
    }

    /**
     * Formatea la respuesta de la IA convirtiendo markdown básico a HTML
     * y dividiendo el texto en párrafos legibles automáticamente.
     */
    function formatAIResponse(text) {
        if (!text) return "";

        // 0. Pre-limpiar timestamps incrustados del tipo "02:14" que pueden
        //    filtrarse desde subtítulos VTT de YouTube
        text = text.replace(/\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*/g, '');

        // 1. Escapar HTML básico por seguridad
        let t = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // 2. Markdown → HTML
        t = t
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-bold">$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Bullet points: • o - al inicio de línea
            .replace(/^[•\-]\s+(.+)$/gm, '<li class="ml-4 list-disc">$1</li>');

        // 3. Dividir en párrafos
        if (t.includes('\n\n')) {
            // Texto con párrafos explícitos (respuesta de IA limpiada)
            return t.split('\n\n')
                .map(p => p.trim())
                .filter(p => p)
                .map(p => {
                    const inner = p.replace(/\n/g, '<br>');
                    if (inner.includes('<li')) return `<ul class="space-y-1 mb-4">${inner}</ul>`;
                    return `<p class="transcript-paragraph">${inner}</p>`;
                })
                .join('');
        }

        if (t.includes('\n')) {
            // Texto con saltos simples
            return t.split('\n')
                .filter(l => l.trim())
                .map(l => `<p class="transcript-paragraph">${l}</p>`)
                .join('');
        }

        // 4. Texto plano sin saltos — dividir por oraciones de a 3 (más respirable)
        const sentences = t.match(/[^.!?]+[.!?]+["']?\s*/g);
        if (sentences && sentences.length > 2) {
            const paragraphs = [];
            const groupSize = sentences.length > 20 ? 3 : 4; // grupos más chicos para transcripciones largas
            for (let i = 0; i < sentences.length; i += groupSize) {
                const chunk = sentences.slice(i, i + groupSize).join('').trim();
                if (chunk) paragraphs.push(`<p class="transcript-paragraph">${chunk}</p>`);
            }
            return paragraphs.join('');
        }

        // 5. Último recurso: texto sin signos de puntuación.
        // Dividir en párrafos cada 55 palabras.
        const words = t.split(/\s+/).filter(w => w);
        if (words.length > 55) {
            const paragraphs = [];
            for (let i = 0; i < words.length; i += 55) {
                const chunk = words.slice(i, i + 55).join(' ').trim();
                if (chunk) paragraphs.push(`<p class="transcript-paragraph">${chunk}</p>`);
            }
            return paragraphs.join('');
        }

        // Texto corto: párrafo único
        return `<p class="transcript-paragraph">${t}</p>`;
    }
    // ─── AI CHAT LOGIC ──────────────────────────────────────────────────────────
    const chatInput    = document.getElementById('chat-input');
    const chatSendBtn  = document.getElementById('chat-send-btn');
    const chatResponse = document.getElementById('chat-response');

    chatSendBtn?.addEventListener('click', async () => {
        const question = chatInput?.value.trim();
        if (!question) return;
        if (!currentTranscript) { showToast('Esperá a que termine la transcripción', 'error'); return; }

        // Agregar mensaje del usuario al historial
        const chatHistory = document.getElementById('chat-history');
        if (chatHistory) {
            const userBubble = document.createElement('div');
            userBubble.className = 'flex items-start gap-3 justify-end fade-in';
            userBubble.innerHTML = `
                <div class="bg-primary/20 border border-primary/20 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-slate-200 max-w-[85%]">
                    ${question.replace(/</g, '&lt;')}
                </div>
                <span class="material-symbols-outlined text-primary text-base mt-0.5 flex-shrink-0">person</span>`;
            chatHistory.appendChild(userBubble);
        }

        chatInput.value = '';
        chatInput.disabled = true;
        chatSendBtn.disabled = true;

        // Burbuja de carga
        const loadingBubble = document.createElement('div');
        loadingBubble.className = 'flex items-start gap-3 fade-in';
        loadingBubble.innerHTML = `
            <span class="material-symbols-outlined text-primary text-base mt-0.5 flex-shrink-0">smart_toy</span>
            <div class="bg-white/5 border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-400 flex items-center gap-2">
                <div class="w-3 h-3 border-2 border-primary/20 border-t-primary rounded-full animate-spin"></div>
                Pensando...
            </div>`;
        chatHistory?.appendChild(loadingBubble);
        chatResponse?.classList.remove('hidden');
        loadingBubble.scrollIntoView({ behavior: 'smooth', block: 'end' });

        try {
            const r = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: videoUrlInput.value, 
                    question: question,
                    transcript: currentTranscript,
                    groq_api_key: localStorage.getItem(GROQ_KEY_STORE) || undefined
                })
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en el chat');

            // Reemplazar burbuja de carga con la respuesta
            loadingBubble.innerHTML = `
                <span class="material-symbols-outlined text-primary text-base mt-0.5 flex-shrink-0">smart_toy</span>
                <div class="bg-white/5 border border-white/5 rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm text-slate-200 leading-relaxed whitespace-pre-wrap max-w-[85%]">
                    ${formatAIResponse(data.answer)}
                </div>`;
        } catch (err) {
            loadingBubble.innerHTML = `
                <span class="material-symbols-outlined text-red-400 text-base mt-0.5 flex-shrink-0">error</span>
                <div class="bg-red-500/10 border border-red-500/20 rounded-2xl px-4 py-2.5 text-sm text-red-400">${err.message}</div>`;
        } finally {
            chatInput.disabled = false;
            chatSendBtn.disabled = false;
            chatInput.focus();
            loadingBubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    });

    chatInput?.addEventListener('keypress', e => { if (e.key === 'Enter') chatSendBtn?.click(); });

    // ─── SYSTEM MAINTENANCE ─────────────────────────────────────────────────────
    const callSystemEndpoint = async (endpoint, btn) => {
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<div class="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center animate-spin"><span class="material-symbols-outlined">sync</span></div><div class="text-left"><p class="text-sm font-bold text-white">Procesando...</p></div>`;
        
        try {
            const r = await fetch(`${API_BASE}/system/${endpoint}`, { method: 'POST' });
            const d = await r.json();
            if (r.ok) {
                showToast(d.message, 'success');
                if (endpoint === 'update-app') {
                    setTimeout(() => window.location.reload(), 2000);
                }
            } else {
                throw new Error(d.error || 'Fallo en la operacion');
            }
        } catch (e) {
            showToast(e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    };

    document.getElementById('system-update-app-btn')?.addEventListener('click', (e) => callSystemEndpoint('update-app', e.currentTarget));
    document.getElementById('system-update-engine-btn')?.addEventListener('click', (e) => callSystemEndpoint('update-engine', e.currentTarget));
    document.getElementById('system-reset-btn')?.addEventListener('click', (e) => {
        if (confirm('¿Vaciar la carpeta de descargas? No se borrará tu historial.')) {
            callSystemEndpoint('reset', e.currentTarget);
        }
    });


});
