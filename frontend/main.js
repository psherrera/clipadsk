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

    // ─── CONFIG ─────────────────────────────────────────────────────────────────
    const isLocal      = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:';
    const isSharedPort = window.location.port === '5000' || window.location.port === '10000';
    const API_BASE     = (isLocal && !isSharedPort) ? 'http://127.0.0.1:5000/api' : '/api';
    const APP_PASSWORD = 'acceso';

    let currentTab             = 'youtube';
    let currentTranscript      = '';
    let currentMaxResThumbnail = '';

    // ─── PLATFORM DETECTION ─────────────────────────────────────────────────────
    const PLATFORMS = {
        youtube:   { hosts: ['youtube.com', 'youtu.be'],             icon: 'subscriptions', label: 'YouTube',   placeholder: 'Pega el enlace de YouTube...' },
        instagram: { hosts: ['instagram.com'],                        icon: 'photo_library', label: 'Instagram', placeholder: 'Pega el enlace del Reel o Video...' },
        tiktok:    { hosts: ['tiktok.com', 'vm.tiktok.com'],         icon: 'music_note',    label: 'TikTok',    placeholder: 'Pega el enlace de TikTok...' },
        twitter:   { hosts: ['twitter.com', 'x.com', 't.co'],       icon: 'tag',           label: 'Twitter/X', placeholder: 'Pega el enlace del tweet con video...' },
        facebook:  { hosts: ['facebook.com', 'fb.watch', 'fb.com'], icon: 'group',         label: 'Facebook',  placeholder: 'Pega el enlace del video de Facebook...' },
        whatsapp:  { hosts: [],                                       icon: 'mic',           label: 'WhatsApp',  placeholder: 'Sube un audio de WhatsApp (.ogg/.mp3)' },
    };

    function detectPlatformFromUrl(url) {
        for (const [key, cfg] of Object.entries(PLATFORMS)) {
            if (cfg.hosts.some(h => url.includes(h))) return key;
        }
        return 'youtube';
    }

    // ─── HISTORY ─────────────────────────────────────────────────────────────────
    const HISTORY_KEY = 'clipadsk_history';

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
                    <p class="text-sm">Aun no hay transcripciones guardadas.</p>
                    <p class="text-xs mt-1 opacity-60">Se guardan automaticamente al transcribir.</p>
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
            if (tabTitle)    tabTitle.textContent    = `${cfg.label} Transcriptor`;
            if (appSubtitle) appSubtitle.textContent = `Transcribi contenido de ${cfg.label} con IA.`;
            if (inputIcon)   inputIcon.textContent   = cfg.icon;
            if (videoUrlInput) videoUrlInput.placeholder = cfg.placeholder;
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
    loginBtn?.addEventListener('click', () => {
        if (passwordInput.value === APP_PASSWORD) {
            loginModal.classList.add('opacity-0');
            setTimeout(() => loginModal.classList.add('hidden'), 400);
            localStorage.setItem('app_logged_in', 'true');
        } else {
            loginError?.classList.remove('hidden');
            passwordInput.value = '';
            loginModal.querySelector('.glass')?.classList.add('animate-bounce');
            setTimeout(() => loginModal.querySelector('.glass')?.classList.remove('animate-bounce'), 500);
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
        downloadBtn.disabled = true;
        downloadProgress?.classList.remove('hidden');

        let progress = 0;
        const interval = setInterval(() => {
            if (progress < 88) { progress += Math.random() * 4; updateProgress(Math.floor(progress), 'Procesando en el servidor...'); }
        }, 700);

        try {
            const r = await fetch(`${API_BASE}/download`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, format_id: formatId }) });
            if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Error en descarga'); }
            clearInterval(interval);
            updateProgress(95, 'Preparando archivo...');
            const blob = await r.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${titleEl.textContent.substring(0, 30).trim() || 'video'}.mp4`;
            document.body.appendChild(a); a.click();
            URL.revokeObjectURL(a.href); a.remove();
            updateProgress(100, 'Descarga completada!');
            setTimeout(() => downloadProgress?.classList.add('hidden'), 4000);
        } catch (err) {
            clearInterval(interval);
            showToast(`Error: ${err.message}`, 'error');
            downloadProgress?.classList.add('hidden');
        } finally { downloadBtn.disabled = false; }
    });

    // ─── TRANSCRIPT FROM URL ─────────────────────────────────────────────────────
    showTranscriptBtn?.addEventListener('click', async () => {
        const url = videoUrlInput?.value.trim();
        transcriptSection?.classList.remove('hidden');
        transcriptSection?.classList.add('fade-in');
        transcriptContent.innerHTML = `
            <div class="flex items-center gap-3 text-slate-400">
                <div class="w-5 h-5 border-2 border-slate-700 border-t-accent rounded-full animate-spin flex-shrink-0"></div>
                <p class="text-sm animate-pulse">Transcribiendo con IA... puede tardar hasta 60 segundos.</p>
            </div>`;
        showTranscriptBtn.disabled = true;

        try {
            const r    = await fetch(`${API_BASE}/transcript`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
            const data = await r.json();

            if (data.error) {
                transcriptContent.innerHTML = `<div class="bg-red-500/10 p-4 rounded-xl border border-red-500/20 text-red-400 text-sm">Error: ${data.error.replace(/\u001b\[[0-9;]*m/g, '')}</div>`;
                return;
            }

            currentTranscript = data.transcript;
            renderTranscript(data.transcript, data.method);
            downloadTxtBtn?.classList.remove('hidden');

            saveToHistory({ url, platform: detectPlatformFromUrl(url), title: titleEl.textContent || url, transcript: data.transcript });

        } catch (err) {
            transcriptContent.innerHTML = `<p class="text-red-400 text-sm">Error al conectar con el servidor.</p>`;
        } finally { showTranscriptBtn.disabled = false; }
    });

    function renderTranscript(text, method) {
        const methodLabels = { subtitles: 'Subtitulos directos', groq_whisper_v3: 'IA Whisper v3 (Groq)', groq_whisper_v3_file: 'IA Whisper v3 - Archivo', cache: 'Cache local' };
        
        // Solo el texto va al contenedor con scroll
        transcriptContent.innerHTML = `<div class="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">${formatAIResponse(text)}</div>`;
        
        // Actualizar etiqueta de metodo
        const methodTag = document.createElement('div');
        methodTag.className = "flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest bg-white/5 py-1 px-3 rounded-full w-fit mt-4 mb-2";
        methodTag.innerHTML = `<span class="material-symbols-outlined text-xs">auto_awesome</span> ${methodLabels[method] || method}`;
        transcriptContent.appendChild(methodTag);

        // Mostrar herramientas y chat
        document.getElementById('ai-chat-section')?.classList.remove('hidden');
        
        // Inyectar herramientas si no estan
        const toolsContainer = document.getElementById('journalist-tools-wrapper');
        if (toolsContainer) {
            toolsContainer.innerHTML = buildJournalistToolsHtml('vc');
            toolsContainer.classList.remove('hidden');
        }
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
        <div id="${prefix}-tools-container" class="border-t border-white/5 pt-4 mt-2">
            <div class="flex items-center gap-2 mb-3">
                <span class="bg-primary/20 text-primary p-1.5 rounded-lg flex items-center"><span class="material-symbols-outlined text-sm">newspaper</span></span>
                <h5 class="font-bold text-white text-sm">Herramientas periodisticas</h5>
            </div>
            <div class="grid grid-cols-2 gap-2">
                <button data-tool="summary" data-prefix="${prefix}" class="j-tool-btn bg-white/5 hover:bg-primary/20 border border-white/5 py-3 px-3 rounded-xl text-slate-300 text-xs font-bold flex items-center gap-2 transition-all">
                    <span class="material-symbols-outlined text-base text-primary">summarize</span> Resumen
                </button>
                <button data-tool="quotes" data-prefix="${prefix}" class="j-tool-btn bg-white/5 hover:bg-accent/20 border border-white/5 py-3 px-3 rounded-xl text-slate-300 text-xs font-bold flex items-center gap-2 transition-all">
                    <span class="material-symbols-outlined text-base text-accent">format_quote</span> Citas
                </button>
                <button data-tool="data" data-prefix="${prefix}" class="j-tool-btn bg-white/5 hover:bg-orange-500/20 border border-white/5 py-3 px-3 rounded-xl text-slate-300 text-xs font-bold flex items-center gap-2 transition-all">
                    <span class="material-symbols-outlined text-base text-orange-400">data_object</span> Datos duros
                </button>
                <button data-tool="angle" data-prefix="${prefix}" class="j-tool-btn bg-white/5 hover:bg-emerald-500/20 border border-white/5 py-3 px-3 rounded-xl text-slate-300 text-xs font-bold flex items-center gap-2 transition-all">
                    <span class="material-symbols-outlined text-base text-emerald-400">lightbulb</span> Angulos de nota
                </button>
            </div>
            <div id="${prefix}-ai-output" class="hidden mt-4 bg-black/30 rounded-2xl p-5 border border-white/5 fade-in"></div>
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
            showToast('Primero transcribi un audio o video', 'error'); return;
        }

        const outputEl = document.getElementById(`${prefix}-ai-output`);
        if (!outputEl) return;

        const cfg = {
            summary : { label: 'Resumen ejecutivo', icon: 'summarize',    color: 'text-primary' },
            quotes  : { label: 'Citas textuales',   icon: 'format_quote', color: 'text-accent' },
            data    : { label: 'Datos duros',        icon: 'data_object',  color: 'text-orange-400' },
            angle   : { label: 'Angulos de nota',    icon: 'lightbulb',    color: 'text-emerald-400' },
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
            const r    = await fetch(`${API_BASE}/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ transcript: currentTranscript, mode }) });
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
                <div class="ai-result-text text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">${formatAIResponse(data.result)}</div>`;

        } catch (err) {
            outputEl.innerHTML = `<p class="text-red-400 text-xs">Error: ${err.message}</p>`;
        }
    });

    // ─── COPY / DOWNLOAD (card de video) ────────────────────────────────────────
    copyTranscriptBtn?.addEventListener('click', () => {
        if (!currentTranscript) return;
        navigator.clipboard.writeText(currentTranscript);
        const orig = copyTranscriptBtn.innerHTML;
        copyTranscriptBtn.innerHTML = '<span class="material-symbols-outlined text-sm">check</span> COPIADO';
        setTimeout(() => { copyTranscriptBtn.innerHTML = orig; }, 2000);
    });

    downloadTxtBtn?.addEventListener('click', () => {
        if (!currentTranscript) return;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([currentTranscript], { type: 'text/plain' }));
        a.download = `${titleEl?.textContent.substring(0, 30) || 'transcripcion'}.txt`;
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
     * Formatea la respuesta de la IA convirtiendo markdown basico a HTML
     * y asegurando que los saltos de linea se respeten.
     */
    function formatAIResponse(text) {
        if (!text) return "";
        let formatted = text
            // Negritas: **texto** -> <b>texto</b>
            .replace(/\*\*(.*?)\*\*/g, '<b class="text-white font-bold">$1</b>')
            // Cursivas: *texto* -> <i>texto</i>
            .replace(/\*(.*?)\*/g, '<i>$1</i>');
        
        return formatted;
    }
    // ─── AI CHAT LOGIC ──────────────────────────────────────────────────────────
    const chatInput    = document.getElementById('chat-input');
    const chatSendBtn  = document.getElementById('chat-send-btn');
    const chatResponse = document.getElementById('chat-response');

    chatSendBtn?.addEventListener('click', async () => {
        const question = chatInput?.value.trim();
        if (!question) return;
        if (!currentTranscript) { showToast('Espera a que termine la transcripcion', 'error'); return; }

        chatInput.value = '';
        chatInput.disabled = true;
        chatSendBtn.disabled = true;
        
        chatResponse.classList.remove('hidden');
        chatResponse.innerHTML = `
            <div class="flex items-center gap-3">
                <div class="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin"></div>
                <p class="text-xs text-slate-400 animate-pulse">Pensando...</p>
            </div>`;

        try {
            const r = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: videoUrlInput.value, 
                    question: question,
                    transcript: currentTranscript 
                })
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Error en el chat');

            chatResponse.innerHTML = `
                <div class="flex items-start gap-3">
                    <span class="material-symbols-outlined text-primary text-base mt-0.5">smart_toy</span>
                    <div class="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">${formatAIResponse(data.answer)}</div>
                </div>`;
        } catch (err) {
            chatResponse.innerHTML = `<p class="text-red-400 text-xs">Error: ${err.message}</p>`;
        } finally {
            chatInput.disabled = false;
            chatSendBtn.disabled = false;
            chatInput.focus();
        }
    });

    chatInput?.addEventListener('keypress', e => { if (e.key === 'Enter') chatSendBtn?.click(); });

});
