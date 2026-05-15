/**
 * Clipadsk - Frontend v2.0
 * Herramienta de transcripción para periodistas y comunicadores.
 * Mejoras: WhatsApp upload, TikTok/Twitter/Facebook, herramientas periodísticas, historial.
 */
document.addEventListener('DOMContentLoaded', () => {

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
    const appSubtitle          = document.getElementById('app-subtitle');
    const tabTitle             = document.getElementById('tab-title');
    const inputIcon            = document.getElementById('input-icon');
    const loginModal           = document.getElementById('login-modal');
    const loginBtn             = document.getElementById('login-btn');
    const passwordInput        = document.getElementById('app-password');
    const loginError           = document.getElementById('login-error');
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

    let currentTab             = 'youtube';
    let currentTranscript      = '';
    let currentMaxResThumbnail = '';

    // ─── PLATFORM DETECTION ─────────────────────────────────────────────────────
    const PLATFORMS = {
        youtube:   { hosts: ['youtube.com', 'youtu.be'],             icon: 'subscriptions', label: 'YouTube',   placeholder: 'Pega el enlace de YouTube...' },
        instagram: { hosts: ['instagram.com'],                        icon: 'photo_library', label: 'Instagram', placeholder: 'Pega el enlace del Reel o Video...' },
        redes:     { hosts: ['tiktok.com', 'vm.tiktok.com', 'twitter.com', 'x.com', 't.co', 'facebook.com', 'fb.watch', 'fb.com'], icon: 'share', label: 'Redes (TikTok/X/FB)', placeholder: 'Pega enlace de TikTok, X o Facebook...' },
        whatsapp:  { hosts: [],                                       icon: 'mic',           label: 'WhatsApp',  placeholder: 'Sube un audio de WhatsApp (.ogg/.mp3)' },
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
            const preview = item.transcript ? item.transcript.substring(0, 140) + '...' : 'Sin transcripcion';
            return `
            <div class="glass rounded-2xl p-5 space-y-3 fade-in">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="material-symbols-outlined text-primary text-lg flex-shrink-0">${platformIcon}</span>
                        <span class="text-white font-semibold text-sm truncate">${item.title || item.url}</span>
                    </div>
                    <span class="text-slate-500 text-[10px] flex-shrink-0 font-mono">${date}</span>
                </div>
                ${item.transcript ? `
                <p class="text-slate-400 text-xs leading-relaxed line-clamp-2">${preview}</p>
                <div class="flex gap-2 flex-wrap">
                    <button onclick="window._hist.copy(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-accent/20 text-accent px-3 py-1.5 rounded-full hover:bg-accent/30 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">content_copy</span> Copiar
                    </button>
                    <button onclick="window._hist.download(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-white/5 text-slate-300 px-3 py-1.5 rounded-full hover:bg-white/10 transition-all flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">download</span> .txt
                    </button>
                    <button onclick="window._hist.remove(${i})" class="text-[10px] font-bold uppercase tracking-widest bg-red-500/10 text-red-400 px-3 py-1.5 rounded-full hover:bg-red-500/20 transition-all flex items-center gap-1 ml-auto">
                        <span class="material-symbols-outlined text-xs">delete</span>
                    </button>
                </div>` : ''}
            </div>`;
        }).join('');
    }

    window._hist = {
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
        remove: (i) => {
            const history = getHistory();
            history.splice(i, 1);
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
            renderHistory();
        }
    };

    // ─── TAB SWITCHING ───────────────────────────────────────────────────────────
    function switchTab(tab) {
        currentTab = tab;
        navItems.forEach(i => { i.classList.remove('active', 'text-primary'); i.classList.add('text-slate-500'); });
        const activeNav = document.querySelector(`[data-tab="${tab}"]`);
        if (activeNav) { activeNav.classList.add('active', 'text-primary'); activeNav.classList.remove('text-slate-500'); }

        const cfg         = PLATFORMS[tab];
        const mainSection = document.getElementById('main-input-section');
        const waSection   = document.getElementById('whatsapp-section');
        const histSection = document.getElementById('history-section');

        mainSection?.classList.toggle('hidden', tab === 'whatsapp' || tab === 'history');
        waSection?.classList.toggle('hidden', tab !== 'whatsapp');
        histSection?.classList.toggle('hidden', tab !== 'history');
        videoInfoCard?.classList.add('hidden');

        if (cfg) {
            if (tabTitle)    tabTitle.textContent    = tab === 'history' ? 'Configuración y Guardados' : `${cfg.label} Transcriptor`;
            if (appSubtitle) appSubtitle.textContent = tab === 'history' ? 'Ajustes, claves de API y transcripciones locales.' : `Transcribí contenido de ${cfg.label} con IA.`;
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

    // ─── LOGIN ───────────────────────────────────────────────────────────────────
    loginBtn?.addEventListener('click', async () => {
        const pass = passwordInput.value;
        const oldText = loginBtn.textContent;
        loginBtn.textContent = "Verificando...";
        loginBtn.disabled = true;
        
        try {
            const r = await fetch(`${API_BASE}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: pass })
            });
            
            if (r.ok) {
                loginModal.classList.add('opacity-0');
                setTimeout(() => loginModal.classList.add('hidden'), 400);
                localStorage.setItem('app_logged_in', 'true');
            } else {
                throw new Error("Contraseña incorrecta");
            }
        } catch (e) {
            loginError?.classList.remove('hidden');
            passwordInput.value = '';
            loginModal.querySelector('.glass')?.classList.add('animate-bounce');
            setTimeout(() => loginModal.querySelector('.glass')?.classList.remove('animate-bounce'), 500);
        } finally {
            loginBtn.textContent = oldText;
            loginBtn.disabled = false;
        }
    });
    passwordInput?.addEventListener('keypress', e => { if (e.key === 'Enter') loginBtn?.click(); });
    if (localStorage.getItem('app_logged_in') === 'true') loginModal?.classList.add('hidden');

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

        const uid = Math.random().toString(36).substring(2, 15);
        const interval = setInterval(async () => {
            try {
                const r = await fetch(`${API_BASE}/progress/${uid}`);
                if (r.ok) {
                    const data = await r.json();
                    updateProgress(data.progress || 0, data.text || 'Procesando en el servidor...');
                }
            } catch (e) {}
        }, 800);

        try {
            const bodyData = { url, format_id: formatId, uid };
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
            a.download = `${filename}.mp4`;
            
            document.body.appendChild(a); a.click();
            URL.revokeObjectURL(a.href); a.remove();
            updateProgress(100, 'Descarga completada!');
            setTimeout(() => downloadProgress?.classList.add('hidden'), 4000);
        } catch (err) {
            clearInterval(interval);
            showToast(`Error: ${err.message}`, 'error');
            downloadProgress?.classList.add('hidden');
        } finally { 
            clearInterval(interval);
            downloadBtn.disabled = false; 
        }
    });

    // ─── TRANSCRIPT FROM URL ─────────────────────────────────────────────────────
    showTranscriptBtn?.addEventListener('click', async () => {
        const url = videoUrlInput?.value.trim();
        transcriptSection?.classList.remove('hidden');
        transcriptSection?.classList.add('fade-in');
        transcriptContent.innerHTML = `
            <div class="flex items-center gap-3 text-slate-400">
                <div class="w-5 h-5 border-2 border-slate-700 border-t-accent rounded-full animate-spin flex-shrink-0"></div>
                <p id="transcript-progress-text" class="text-sm animate-pulse">Iniciando proceso...</p>
            </div>`;
        showTranscriptBtn.disabled = true;

        const uid = Math.random().toString(36).substring(2, 15);
        const pollInterval = setInterval(async () => {
            try {
                const r = await fetch(`${API_BASE}/progress/${uid}`);
                if (r.ok) {
                    const data = await r.json();
                    const textEl = document.getElementById('transcript-progress-text');
                    if (textEl && data.text) {
                        textEl.textContent = `${data.text} (${data.progress}%)`;
                    }
                }
            } catch (e) {}
        }, 800);

        try {
            const reqBody = { url, groq_api_key: localStorage.getItem(GROQ_KEY_STORE) || undefined, uid };
            const r    = await fetch(`${API_BASE}/transcript`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reqBody) });
            const data = await r.json();

            clearInterval(pollInterval);

            if (data.error) {
                transcriptContent.innerHTML = `<div class="bg-red-500/10 p-4 rounded-xl border border-red-500/20 text-red-400 text-sm">Error: ${data.error.replace(/\u001b\[[0-9;]*m/g, '')}</div>`;
                return;
            }

            currentTranscript = data.transcript;
            renderTranscript(data.transcript, data.method);
            downloadTxtBtn?.classList.remove('hidden');

            saveToHistory({ url, platform: detectPlatformFromUrl(url), title: titleEl.textContent || url, transcript: data.transcript });

        } catch (err) {
            clearInterval(pollInterval);
            transcriptContent.innerHTML = `<p class="text-red-400 text-sm">Error al conectar con el servidor.</p>`;
        } finally { 
            clearInterval(pollInterval);
            showTranscriptBtn.disabled = false; 
        }
    });

    function renderTranscript(text, method) {
        const methodLabels = { subtitles: 'Subtítulos directos', groq_whisper_v3: 'IA Whisper v3 (Groq)', groq_whisper_v3_file: 'IA Whisper v3 - Archivo', cache: 'Caché local' };
        
        // 1. Inyectar herramientas ARRIBA (antes del texto)
        const toolsContainer = document.getElementById('journalist-tools-wrapper');
        if (toolsContainer) {
            toolsContainer.innerHTML = buildJournalistToolsHtml('vc');
            toolsContainer.classList.remove('hidden');
        }

        // 2. Texto de transcripción con etiqueta de método
        transcriptContent.innerHTML = `
            <div class="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest bg-white/5 py-1 px-3 rounded-full w-fit mb-4">
                <span class="material-symbols-outlined text-xs">auto_awesome</span>
                ${methodLabels[method] || method}
            </div>
            <div class="text-slate-300 text-sm leading-relaxed">${formatAIResponse(text)}</div>`;

        // 3. Mostrar sección de chat
        document.getElementById('ai-chat-section')?.classList.remove('hidden');
        // Limpiar historial de chat al cargar nueva transcripción
        const chatHistory = document.getElementById('chat-history');
        if (chatHistory) chatHistory.innerHTML = '';
    }

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
        formData.append('language', 'es');
        formData.append('groq_api_key', localStorage.getItem(GROQ_KEY_STORE) || '');

        try {
            const r    = await fetch(`${API_BASE}/transcript-file`, { method: 'POST', body: formData });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en la transcripcion');

            currentTranscript = data.transcript;

            if (waResult) {
                waResult.classList.remove('hidden'); waResult.classList.add('fade-in');
                waResult.innerHTML = `
                    <div class="space-y-4">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center gap-2">
                                <span class="bg-emerald-500/20 text-emerald-400 p-1.5 rounded-lg flex items-center"><span class="material-symbols-outlined text-sm">check_circle</span></span>
                                <span class="text-white font-bold text-sm">Transcripcion lista</span>
                            </div>
                            <span class="text-slate-500 text-xs">${data.size_mb} MB</span>
                        </div>
                        <p class="text-slate-300 text-sm leading-relaxed border border-white/5 rounded-xl p-4 bg-black/20">${data.transcript}</p>
                        <div class="flex gap-2 flex-wrap">
                            <button onclick="window._wa.copy()" class="text-[10px] font-bold uppercase tracking-widest bg-accent/20 text-accent px-3 py-2 rounded-full hover:bg-accent/30 transition-all flex items-center gap-1">
                                <span class="material-symbols-outlined text-xs">content_copy</span> Copiar
                            </button>
                            <button onclick="window._wa.download('${file.name}')" class="text-[10px] font-bold uppercase tracking-widest bg-white/5 text-slate-300 px-3 py-2 rounded-full hover:bg-white/10 transition-all flex items-center gap-1">
                                <span class="material-symbols-outlined text-xs">download</span> .txt
                            </button>
                        </div>
                        ${buildJournalistToolsHtml('wa')}
                    </div>`;
            }

            saveToHistory({ url: `whatsapp:${file.name}`, platform: 'whatsapp', title: file.name, transcript: data.transcript });

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

    // ─── JOURNALIST TOOLS ────────────────────────────────────────────────────────
    function buildJournalistToolsHtml(prefix) {
        return `
        <div id="${prefix}-tools-container">
            <div class="flex items-center gap-2 mb-4">
                <span class="bg-primary/20 text-primary p-1.5 rounded-lg flex items-center"><span class="material-symbols-outlined text-sm">newspaper</span></span>
                <h5 class="font-bold text-white text-sm">Herramientas periodísticas</h5>
                <span class="ml-auto text-[10px] font-bold text-slate-600 uppercase tracking-widest">IA</span>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
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
                    <span>Ángulos de nota</span>
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

        const cfg = {
            summary : { label: 'Resumen ejecutivo',  icon: 'summarize',    color: 'text-primary' },
            quotes  : { label: 'Citas textuales',    icon: 'format_quote', color: 'text-accent' },
            data    : { label: 'Datos duros',        icon: 'data_object',  color: 'text-orange-400' },
            angle   : { label: 'Ángulos de nota',    icon: 'lightbulb',    color: 'text-emerald-400' },
        }[mode];

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
    });

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

    downloadTxtBtn?.addEventListener('click', () => {
        if (!currentTranscript) return;
        const title = (titleEl?.textContent || 'transcripcion').trim().substring(0, 60);
        const safeTitle = title.replace(/[/\\?%*:|"<>]/g, '-');
        const header = `${title}\n${'─'.repeat(Math.min(title.length, 60))}\n\n`;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([header + getFormattedPlainText()], { type: 'text/plain;charset=utf-8' }));
        a.download = `${safeTitle}.txt`;
        a.click();
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
                    // Si es lista, envolver en <ul>
                    if (inner.includes('<li')) return `<ul class="space-y-1 mb-3">${inner}</ul>`;
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

        // 4. Texto plano sin saltos — intentar dividir por oraciones (. ! ?)
        const sentences = t.match(/[^.!?]+[.!?]+["']?\s*/g);
        if (sentences && sentences.length > 3) {
            const paragraphs = [];
            for (let i = 0; i < sentences.length; i += 4) {
                const chunk = sentences.slice(i, i + 4).join('').trim();
                if (chunk) paragraphs.push(`<p class="transcript-paragraph">${chunk}</p>`);
            }
            return paragraphs.join('');
        }

        // 5. Último recurso: texto sin signos de puntuación (letra de canción, stream).
        // Dividir en párrafos cada 70 palabras para que sea legible.
        const words = t.split(/\s+/).filter(w => w);
        if (words.length > 70) {
            const paragraphs = [];
            for (let i = 0; i < words.length; i += 70) {
                const chunk = words.slice(i, i + 70).join(' ').trim();
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

});
