/**
 * Clipadsk 3.0 — funciones nuevas.
 * Se carga ANTES que main.js: define window.ClipaV3 (historial en el servidor, trabajos en
 * segundo plano, diálogos, citas). Cuando main.js termina de arrancar dispara "clipa:ready"
 * con sus funciones en window.Clipa, y recién ahí se montan las partes de la interfaz
 * (visualizador, panel de trabajos, aviso de cookies, atajos, arrastrar archivos).
 */
(function () {
    'use strict';

    // ─── Utilidades ──────────────────────────────────────────────────────────────
    const host = window.location.hostname;
    const isLocal = host === 'localhost' || host === '127.0.0.1' || window.location.protocol === 'file:';
    const isSharedPort = window.location.port === '5000' || window.location.port === '10000';
    const API = (isLocal && !isSharedPort) ? 'http://127.0.0.1:5000/api' : '/api';
    const MEDIA_BASE = API.replace(/\/api$/, '');
    const GROQ_KEY_STORE = 'clipadsk_groq_api_key';

    const $ = (sel, root = document) => root.querySelector(sel);
    const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    const store = {
        get(k) { try { return localStorage.getItem(k); } catch { return null; } },
        set(k, v) { try { localStorage.setItem(k, v); } catch { /* lleno o bloqueado */ } },
        del(k) { try { localStorage.removeItem(k); } catch { /* nada */ } },
    };
    const groqKey = () => store.get(GROQ_KEY_STORE) || undefined;
    const uid = () => Math.random().toString(36).slice(2, 12);
    const toast = (msg, type = 'info', ms) => window.Clipa?.showToast ? window.Clipa.showToast(msg, type, ms) : console.log(msg);

    /** 75.4 → "1:15", 3725 → "1:02:05" */
    function fmtTime(sec, withTenths = false) {
        sec = Math.max(0, Number(sec) || 0);
        const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
        const tenths = withTenths ? `.${Math.floor((sec % 1) * 10)}` : '';
        const mm = h ? String(m).padStart(2, '0') : String(m);
        return `${h ? h + ':' : ''}${mm}:${String(s).padStart(2, '0')}${tenths}`;
    }

    /** "1:02:05" / "75" / "1:15.5" → segundos (o null) */
    function parseTime(str) {
        const t = String(str || '').trim().replace(',', '.');
        if (!t) return null;
        if (!/^\d+(:\d{1,2}){0,2}(\.\d+)?$/.test(t)) return null;
        return t.split(':').reduce((acc, p) => acc * 60 + parseFloat(p), 0);
    }

    async function api(path, { method = 'GET', body, signal, form } = {}) {
        const opts = { method, signal };
        if (form) opts.body = form;
        else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers = { 'Content-Type': 'application/json' }; }
        const r = await fetch(`${API}${path}`, opts);
        const isJson = (r.headers.get('content-type') || '').includes('json');
        const data = isJson ? await r.json().catch(() => ({})) : null;
        if (!r.ok) {
            const err = new Error((data && (data.detail || data.error)) || `Error ${r.status} del servidor`);
            err.status = r.status;
            throw err;
        }
        return isJson ? data : r;
    }

    function downloadBlob(blob, filename) {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    }

    function filenameFrom(response, fallback) {
        const cd = response.headers.get('content-disposition') || '';
        const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
        if (star) { try { return decodeURIComponent(star[1]); } catch { /* sigue */ } }
        const plain = cd.match(/filename="?([^";]+)"?/i);
        return plain ? plain[1] : fallback;
    }

    // ─── Diálogos propios (reemplazan confirm() y prompt() del navegador) ────────
    function dialog({ title = 'Clipadsk', message = '', okText = 'Aceptar', cancelText = 'Cancelar',
                      input = false, placeholder = '', danger = false, html = false } = {}) {
        return new Promise(resolve => {
            const prevFocus = document.activeElement;
            const wrap = document.createElement('div');
            wrap.className = 'v3-modal-backdrop';
            wrap.innerHTML = `
                <div class="v3-modal" role="dialog" aria-modal="true" aria-labelledby="v3-modal-title">
                    <h3 id="v3-modal-title">${esc(title)}</h3>
                    <div class="v3-modal-body">${html ? message : `<p>${esc(message)}</p>`}</div>
                    ${input ? `<input class="field w-full v3-modal-input" type="${input === 'password' ? 'password' : 'text'}" placeholder="${esc(placeholder)}" autocomplete="off">` : ''}
                    <div class="v3-modal-actions">
                        ${cancelText ? `<button class="btn-ghost" data-act="cancel">${esc(cancelText)}</button>` : ''}
                        <button class="btn-primary ${danger ? 'v3-danger' : ''}" data-act="ok">${esc(okText)}</button>
                    </div>
                </div>`;
            const field = wrap.querySelector('.v3-modal-input');
            const close = (value) => {
                wrap.remove();
                document.removeEventListener('keydown', onKey, true);
                prevFocus?.focus?.();
                resolve(value);
            };
            const ok = () => close(input ? (field.value.trim() || null) : true);
            const cancel = () => close(input ? null : false);
            const onKey = (e) => {
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancel(); }
                if (e.key === 'Enter' && (input || document.activeElement?.dataset?.act !== 'cancel')) { e.preventDefault(); e.stopPropagation(); ok(); }
            };
            wrap.addEventListener('click', e => {
                if (e.target === wrap) cancel();
                const act = e.target.closest('[data-act]')?.dataset.act;
                if (act === 'ok') ok();
                if (act === 'cancel') cancel();
            });
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(wrap);
            (field || wrap.querySelector('[data-act="ok"]')).focus();
        });
    }
    const confirmDialog = (message, opts = {}) => dialog({ message, ...opts });
    const promptDialog = (message, opts = {}) => dialog({ message, input: true, ...opts });

    // ─── Historial (en la base de datos del servidor) ────────────────────────────
    const OLD_HISTORY_KEY = 'clipadsk_history';
    const history = {
        items: [],
        currentId: null,
        loaded: false,

        list() { return this.items; },

        async load() {
            try {
                const res = await api('/history?limit=500');
                this.items = res.items || [];
                this.loaded = true;
            } catch (e) {
                console.warn('No se pudo cargar el historial', e);
            }
            document.dispatchEvent(new CustomEvent('clipa:history'));
            return this.items;
        },

        async search(q) {
            const res = await api(`/history?limit=200&q=${encodeURIComponent(q)}`);
            return res.items || [];
        },

        get(id) { return api(`/history/${encodeURIComponent(id)}`); },

        async save(entry) {
            try {
                const res = await api('/history', { method: 'POST', body: entry });
                this.currentId = res.id;
                await this.load();
                return res.id;
            } catch (e) {
                toast(`No se pudo guardar en el historial: ${e.message}`, 'error');
                return null;
            }
        },

        async update(id, patch) {
            if (!id) return false;
            await api(`/history/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch });
            const item = this.items.find(i => i.id === id);
            if (item && patch.title) item.title = patch.title;
            return true;
        },

        async remove(id) {
            await api(`/history/${encodeURIComponent(id)}`, { method: 'DELETE' });
            if (this.currentId === id) this.currentId = null;
            await this.load();
        },

        async clear() {
            await adminApi('/history', { method: 'DELETE' });
            this.currentId = null;
            await this.load();
        },

        /** Pasa el historial viejo (guardado en el navegador) a la base de datos, una sola vez. */
        async migrateFromBrowser() {
            const raw = store.get(OLD_HISTORY_KEY);
            if (!raw) return 0;
            let items;
            try { items = JSON.parse(raw); } catch { items = []; }
            if (!Array.isArray(items) || !items.length) { store.del(OLD_HISTORY_KEY); return 0; }
            try {
                const res = await api('/history/import', { method: 'POST', body: { items } });
                store.set(OLD_HISTORY_KEY + '_backup', raw.length < 2_000_000 ? raw : '[]');
                store.del(OLD_HISTORY_KEY);
                if (res.imported) toast(`Se pasaron ${res.imported} transcripciones del navegador al historial de la PC.`, 'success', 6000);
                return res.imported;
            } catch (e) {
                console.warn('No se pudo migrar el historial del navegador', e);
                return 0;
            }
        },
    };

    /** fetch con el token de administrador (si el servidor lo pide). */
    async function adminApi(path, opts = {}) {
        const send = () => {
            const token = store.get('clipadsk_admin_token') || '';
            return fetch(`${API}${path}`, { method: opts.method || 'GET', headers: token ? { 'X-ADMIN-TOKEN': token } : {} });
        };
        let r = await send();
        if (r.status === 403) {
            const detail = (await r.clone().json().catch(() => ({}))).detail || '';
            if (/token de administrador/i.test(detail)) {
                const token = await promptDialog('Esta operación pide el token de administrador (ADMIN_TOKEN del archivo .env).',
                    { title: 'Token de administrador', input: 'password', okText: 'Continuar' });
                if (token) { store.set('clipadsk_admin_token', token); r = await send(); }
            }
        }
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            throw new Error(d.detail || d.error || `Error ${r.status}`);
        }
        return r.json().catch(() => ({}));
    }

    // ─── Trabajos en segundo plano ───────────────────────────────────────────────
    const jobs = {
        list: [],
        known: new Map(),   // id → último estado visto (para avisar cuando cambia)
        timer: null,

        async create({ url, lang = 'es', title, uploader, duration }) {
            askNotificationPermission();
            const job = await api('/jobs', { method: 'POST', body: {
                url, target_lang: lang, groq_api_key: groqKey(), title, uploader, duration } });
            this.known.set(job.id, job.status);
            this.poll();
            return job;
        },

        /** Espera a que termine un trabajo. onProgress(pct, texto). Devuelve el resultado. */
        async waitFor(id, { onProgress, signal } = {}) {
            while (true) {
                if (signal?.aborted) throw new DOMException('Cancelado', 'AbortError');
                let job;
                try {
                    job = await api(`/jobs/${id}`, { signal });
                } catch (e) {
                    if (e.name === 'AbortError') throw e;
                    if (e.status === 404) throw new Error('El trabajo se perdió (¿se reinició el servidor?). Volvé a transcribir.');
                    await new Promise(r => setTimeout(r, 2500));   // corte de red momentáneo: reintentar
                    continue;
                }
                if (job.status === 'done') { this.known.set(id, 'done'); return job.result; }
                if (job.status === 'error') {
                    this.known.set(id, 'error');
                    const err = new Error(job.error || 'No se pudo transcribir');
                    err.technical = job.technical;
                    throw err;
                }
                onProgress?.(job.progress || 0, job.text || 'En cola...');
                await new Promise(r => setTimeout(r, 900));
            }
        },

        async refresh() {
            try {
                const res = await api('/jobs');
                this.list = res.jobs || [];
            } catch { return; }
            for (const job of this.list) {
                const before = this.known.get(job.id);
                if (before && before !== job.status && (job.status === 'done' || job.status === 'error')) notifyJob(job);
                this.known.set(job.id, job.status);
            }
            renderJobsPanel();
        },

        poll() {
            if (this.timer) return;
            const tick = async () => {
                await this.refresh();
                const active = this.list.some(j => j.status === 'queued' || j.status === 'running');
                this.timer = active ? setTimeout(tick, 2000) : null;
            };
            this.timer = setTimeout(tick, 300);
        },

        async dismiss(id) {
            await api(`/jobs/${id}`, { method: 'DELETE' }).catch(() => {});
            await this.refresh();
        },
    };

    function askNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().catch(() => {});
        }
    }

    function notifyJob(job) {
        const ok = job.status === 'done';
        const rec = job.kind === 'record';
        const title = rec ? (ok ? 'Grabación guardada' : 'La grabación falló') : (ok ? 'Transcripción lista' : 'No se pudo transcribir');
        const body = `${job.title || job.url}${ok ? '' : ` — ${job.error || ''}`}`;
        toast(`${title}: ${job.title || job.url}`, ok ? 'success' : 'error', 6000);
        if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
            try {
                const n = new Notification(title, { body, icon: 'icon.svg', tag: job.id });
                n.onclick = () => { window.focus(); if (ok && job.history_id) window.Clipa?.openHistory(job.history_id); n.close(); };
            } catch { /* algunos navegadores no permiten notificaciones desde la página */ }
        }
    }

    // ─── Citas listas para pegar ─────────────────────────────────────────────────
    /** Enlace al segundo exacto (YouTube) o el enlace tal cual (otras plataformas). */
    function linkAt(url, seconds) {
        if (!url || /^(whatsapp|video):/.test(url)) return '';
        if (seconds == null) return url;
        try {
            const u = new URL(url);
            const h = u.hostname.replace(/^www\./, '');
            if (h === 'youtu.be' || h.endsWith('youtube.com')) {
                u.searchParams.set('t', `${Math.floor(seconds)}s`);
                return u.toString();
            }
        } catch { /* URL rara: se devuelve tal cual */ }
        return url;
    }

    function formatQuote(quote, { start = null, speaker = '' } = {}) {
        const meta = window.Clipa?.getMeta?.() || {};
        const who = (speaker || meta.uploader || '').trim();
        const source = (meta.title || '').trim();
        let line = `«${String(quote).trim()}»`;
        const parts = [];
        if (who && who !== 'Desconocido') parts.push(who);
        if (source && source !== who) parts.push(source);
        if (start != null) parts.push(`minuto ${fmtTime(start)}`);
        if (parts.length) line += ` — ${parts.join(', ')}`;
        const link = linkAt(meta.url, start);
        return link ? `${line}.\n${link}` : `${line}.`;
    }

    // ─── Estimación de tiempo ────────────────────────────────────────────────────
    function estimateTranscription({ duration, has_subtitles, platform }) {
        const d = Number(duration) || 0;
        if (has_subtitles && platform === 'youtube') return 'menos de 1 minuto (usa los subtítulos del video)';
        if (!d) return null;
        const hasKey = !!groqKey() || window.Clipa?.serverHasGroq;
        // Bajar el audio + Groq (~25 s por hora de audio por parte) + limpieza con IA (~20 s por hora)
        const secs = hasKey ? 15 + d / 60 * 1.2 + d / 3600 * 45 : d * 0.6;
        const mins = Math.max(1, Math.round(secs / 60));
        const how = hasKey ? '' : ' (sin API Key de Groq: transcribe en la PC, es más lento)';
        return `${mins === 1 ? 'alrededor de 1 minuto' : `unos ${mins} minutos`}${how}`;
    }

    // ═════════════════════════════════════════════════════════════════════════════
    //  VISUALIZADOR: reproductor + texto sincronizado + recorte + vista bilingüe
    // ═════════════════════════════════════════════════════════════════════════════

    function youtubeId(url) {
        try {
            const u = new URL(url);
            const h = u.hostname.replace(/^(www\.|m\.)/, '');
            if (h === 'youtu.be') return u.pathname.slice(1).split('/')[0] || null;
            if (h.endsWith('youtube.com')) {
                if (u.searchParams.get('v')) return u.searchParams.get('v');
                const m = u.pathname.match(/^\/(shorts|live|embed)\/([\w-]{6,})/);
                return m ? m[2] : null;
            }
        } catch { /* no es URL */ }
        return null;
    }

    let ytApiPromise = null;
    function loadYouTubeApi() {
        if (window.YT?.Player) return Promise.resolve(window.YT);
        if (ytApiPromise) return ytApiPromise;
        ytApiPromise = new Promise((resolve, reject) => {
            const prev = window.onYouTubeIframeAPIReady;
            window.onYouTubeIframeAPIReady = () => { prev?.(); resolve(window.YT); };
            const s = document.createElement('script');
            s.src = 'https://www.youtube.com/iframe_api';
            s.onerror = () => { ytApiPromise = null; reject(new Error('No se pudo cargar el reproductor de YouTube (¿sin internet?).')); };
            document.head.appendChild(s);
            setTimeout(() => reject(new Error('El reproductor de YouTube tardó demasiado en cargar.')), 20000);
        });
        return ytApiPromise;
    }

    /** Reproductor común: <video>/<audio> o YouTube, con la misma interfaz. */
    function htmlPlayer(el) {
        return {
            kind: 'html', el,
            play: () => el.play().catch(() => {}),
            pause: () => el.pause(),
            paused: () => el.paused,
            time: () => el.currentTime || 0,
            duration: () => el.duration || 0,
            seek: (t) => { el.currentTime = Math.max(0, t); },
            destroy: () => { el.pause(); el.removeAttribute('src'); el.load?.(); },
        };
    }

    async function youtubePlayer(container, videoId, start = 0) {
        const YT = await loadYouTubeApi();
        const holder = document.createElement('div');
        container.appendChild(holder);
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('YouTube no respondió.')), 20000);
            const p = new YT.Player(holder, {
                videoId,
                playerVars: { start: Math.floor(start), rel: 0, modestbranding: 1, playsinline: 1 },
                events: {
                    onReady: () => {
                        clearTimeout(timer);
                        resolve({
                            kind: 'youtube', el: container,
                            play: () => p.playVideo(),
                            pause: () => p.pauseVideo(),
                            paused: () => p.getPlayerState() !== YT.PlayerState.PLAYING,
                            time: () => p.getCurrentTime() || 0,
                            duration: () => p.getDuration() || 0,
                            seek: (t) => p.seekTo(Math.max(0, t), true),
                            destroy: () => { try { p.destroy(); } catch { /* ya no existe */ } },
                        });
                    },
                    onError: (e) => {
                        clearTimeout(timer);
                        const codes = { 101: 'El dueño del video no permite verlo fuera de YouTube.', 150: 'El dueño del video no permite verlo fuera de YouTube.' };
                        reject(Object.assign(new Error(codes[e.data] || 'YouTube no pudo reproducir el video.'), { ytCode: e.data }));
                    },
                },
            });
        });
    }

    /** Segundos en que un segmento se superpone con el tramo [a, b]. */
    const overlap = (s, a, b) => Math.min(s.end, b) - Math.max(s.start, a);

    const viewer = {
        root: null, player: null, source: null, segments: [], peaks: [], translations: null,
        selIn: null, selOut: null, previewStop: null, raf: 0, activeIdx: -1, userScrollUntil: 0,
        searchHits: [], searchPos: -1, localFile: null, kind: 'url',

        /** Llamado cuando se muestra una transcripción nueva. */
        mount({ segments, source }) {
            this.unmount();
            this.segments = (segments || []).filter(s => s && s.text);
            this.source = source || {};
            this.translations = null;
            this.selIn = this.selOut = null;
            if (!this.segments.length) return;

            const anchor = document.getElementById('transcript-content');
            if (!anchor) return;
            const isFile = this.source.kind === 'file';
            const isAudio = isFile && this.source.file && !/^video\//.test(this.source.file.type || '') &&
                !/\.(mp4|mov|mkv|avi|webm)$/i.test(this.source.file.name || '');
            this.root = document.createElement('section');
            this.root.id = 'v3-viewer';
            this.root.className = 'v3-viewer';
            this.root.innerHTML = `
                <div class="v3-viewer-bar">
                    <button class="btn-soft v3-open-btn" data-v="open">
                        <span class="material-symbols-outlined">smart_display</span> Ver y cortar
                    </button>
                    <span class="v3-hint">Reproducí el video con el texto sincronizado, marcá el tramo y descargalo.</span>
                </div>
                <div class="v3-viewer-body hidden">
                    <div class="v3-stage"><div class="v3-media" data-v="media"></div>
                        <div class="v3-loading hidden" data-v="loading"><div class="v3-spinner"></div><p data-v="loading-text">Preparando el video...</p></div>
                    </div>
                    <div class="v3-timeline-wrap">
                        <canvas class="v3-timeline" data-v="timeline" height="64" title="Clic: ir a ese momento. Arrastrar: marcar el tramo a recortar."></canvas>
                        <div class="v3-times"><span data-v="now">0:00</span><span data-v="dur">0:00</span></div>
                    </div>
                    <div class="v3-controls">
                        <button class="icon-btn" data-v="back" title="Atrás 5 s (J)"><span class="material-symbols-outlined">replay_5</span></button>
                        <button class="icon-btn" data-v="play" title="Reproducir / pausar (barra espaciadora)"><span class="material-symbols-outlined">play_arrow</span></button>
                        <button class="icon-btn" data-v="fwd" title="Adelante 5 s (L)"><span class="material-symbols-outlined">forward_5</span></button>
                        <span class="v3-sep"></span>
                        <button class="btn-ghost v3-small" data-v="mark-in" title="Marcar inicio en el momento actual (I)">[ Inicio</button>
                        <input class="field v3-time-input" data-v="in" placeholder="0:00" aria-label="Inicio del recorte">
                        <span class="v3-arrow">→</span>
                        <input class="field v3-time-input" data-v="out" placeholder="0:00" aria-label="Fin del recorte">
                        <button class="btn-ghost v3-small" data-v="mark-out" title="Marcar fin en el momento actual (O)">Fin ]</button>
                        <button class="btn-ghost v3-small" data-v="preview" title="Ver solo el tramo marcado (P)"><span class="material-symbols-outlined text-base">slideshow</span> Ver tramo</button>
                        <button class="btn-ghost v3-small" data-v="clear" title="Quitar la marca">Quitar</button>
                    </div>
                    <div class="v3-cut">
                        <label class="v3-check ${isAudio ? 'v3-disabled' : ''}"><input type="checkbox" data-v="subs" ${isAudio ? 'disabled' : ''}> Subtítulos en el video</label>
                        <label class="v3-check ${isAudio ? 'v3-disabled' : ''}"><input type="checkbox" data-v="vertical" ${isAudio ? 'disabled' : ''}> Vertical 9:16 (redes)</label>
                        <button class="btn-primary" data-v="download"><span class="material-symbols-outlined">content_cut</span> Descargar recorte</button>
                        <button class="btn-ghost v3-small" data-v="copy-sel" title="Copiar el texto del tramo como cita"><span class="material-symbols-outlined text-base">format_quote</span> Copiar cita</button>
                        <span class="v3-cut-status" data-v="cut-status"></span>
                    </div>
                    <div class="v3-list-bar">
                        <div class="field-wrap v3-search">
                            <span class="material-symbols-outlined text-slate-400 text-lg">search</span>
                            <input data-v="search" placeholder="Buscar en la transcripción (Enter: siguiente)" autocomplete="off">
                            <span class="v3-search-count" data-v="search-count"></span>
                        </div>
                        <select class="field v3-lang" data-v="lang" title="Ver la traducción al lado del original, frase por frase">
                            <option value="">Sin traducción</option>
                            <option value="es">Traducir al español</option>
                            <option value="en">Traducir al inglés</option>
                            <option value="pt">Traducir al portugués</option>
                        </select>
                        <label class="v3-check" title="El texto acompaña al video mientras se reproduce"><input type="checkbox" data-v="follow" checked> Seguir</label>
                    </div>
                    <p class="v3-tip">Clic en una frase o palabra para ir a ese momento. Seleccioná un tramo de texto con el mouse para marcar el recorte.</p>
                    <div class="v3-list" data-v="list"></div>
                </div>`;
            anchor.parentNode.insertBefore(this.root, anchor);
            this.q = (name) => this.root.querySelector(`[data-v="${name}"]`);
            this.renderList();
            this.bind();
        },

        unmount() {
            cancelAnimationFrame(this.raf);
            this.player?.destroy();
            this.player = null;
            if (this.objectUrl) { URL.revokeObjectURL(this.objectUrl); this.objectUrl = null; }
            this.root?.remove();
            this.root = null;
            this.peaks = [];
        },

        isOpen() { return !!this.root && !this.q('media')?.closest('.v3-viewer-body')?.classList.contains('hidden'); },

        bind() {
            const q = this.q;
            this.root.addEventListener('click', (e) => {
                const v = e.target.closest('[data-v]')?.dataset.v;
                const actions = {
                    open: () => this.open(),
                    play: () => this.toggle(),
                    back: () => this.skip(-5),
                    fwd: () => this.skip(5),
                    'mark-in': () => this.setIn(this.now()),
                    'mark-out': () => this.setOut(this.now()),
                    preview: () => this.preview(),
                    clear: () => { this.selIn = this.selOut = null; this.syncInputs(); this.draw(); this.markSelection(); },
                    download: () => this.downloadClip(),
                    'copy-sel': () => this.copySelection(),
                    'pick-file': () => this.pickFile(),
                    'load-wave': () => this.loadWaveformForYoutube(),
                };
                if (actions[v]) { e.preventDefault(); actions[v](); }
            });
            q('in').addEventListener('change', () => { const t = parseTime(q('in').value); this.setIn(t); });
            q('out').addEventListener('change', () => { const t = parseTime(q('out').value); this.setOut(t); });
            q('lang').addEventListener('change', () => this.translate(q('lang').value));
            q('search').addEventListener('input', () => this.search(q('search').value));
            q('search').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); this.nextHit(e.shiftKey ? -1 : 1); }
                if (e.key === 'Escape') { q('search').value = ''; this.search(''); }
            });

            const list = q('list');
            list.addEventListener('click', (e) => {
                if (String(window.getSelection?.() || '').trim()) return;   // estaba seleccionando texto
                const w = e.target.closest('[data-ws]');
                const seg = e.target.closest('[data-i]');
                const t = w ? parseFloat(w.dataset.ws) : seg ? this.segments[Number(seg.dataset.i)].start : null;
                if (t == null) return;
                if (!this.player) { this.open().then(() => this.seek(t)); return; }
                this.seek(t);
            });
            list.addEventListener('mouseup', () => setTimeout(() => this.selectionFromText(), 0));
            list.addEventListener('wheel', () => { this.userScrollUntil = Date.now() + 4000; }, { passive: true });
            list.addEventListener('touchmove', () => { this.userScrollUntil = Date.now() + 4000; }, { passive: true });

            this.bindTimeline();
        },

        async open() {
            const body = this.root.querySelector('.v3-viewer-body');
            body.classList.remove('hidden');
            this.q('open').closest('.v3-viewer-bar').classList.add('hidden');
            this.resizeCanvas();
            if (!this.player) await this.loadMedia();
            this.loop();
        },

        setLoading(on, text) {
            this.q('loading').classList.toggle('hidden', !on);
            if (text) this.q('loading-text').textContent = text;
        },

        async loadMedia() {
            const media = this.q('media');
            const src = this.source;
            try {
                if (src.kind === 'file' && src.file) {
                    await this.useFile(src.file);
                    return;
                }
                if (src.kind === 'file') {
                    media.innerHTML = `<div class="v3-empty-media">
                        <span class="material-symbols-outlined">upload_file</span>
                        <p>Para ver este archivo, elegilo de nuevo desde tu PC (no se guarda una copia).</p>
                        <button class="btn-primary" data-v="pick-file">Elegir archivo</button></div>`;
                    return;
                }
                const ytId = youtubeId(src.url);
                if (ytId) {
                    this.setLoading(true, 'Cargando el reproductor de YouTube...');
                    try {
                        this.player = await youtubePlayer(media, ytId);
                        this.kind = 'youtube';
                        this.setLoading(false);
                        this.afterPlayerReady();
                        this.addWaveButton();
                        return;
                    } catch (e) {
                        media.innerHTML = '';
                        toast(`${e.message} Se usa una copia liviana del video.`, 'info', 6000);
                    }
                }
                await this.loadPrepared(src.url);
            } catch (e) {
                this.setLoading(false);
                media.innerHTML = `<div class="v3-empty-media"><span class="material-symbols-outlined">error</span><p>${esc(e.message)}</p>
                    <button class="btn-ghost" data-v="open-retry">Reintentar</button></div>`;
                media.querySelector('[data-v="open-retry"]').onclick = () => { media.innerHTML = ''; this.loadMedia(); };
            }
        },

        async loadPrepared(url) {
            const progressUid = uid();
            this.setLoading(true, 'Preparando una copia liviana del video para verlo...');
            const timer = setInterval(async () => {
                try {
                    const p = await api(`/progress/${progressUid}`);
                    if (p.text) this.setLoading(true, `${p.text}`);
                } catch { /* sigue */ }
            }, 900);
            try {
                const res = await api('/media/prepare', { method: 'POST', body: { url, uid: progressUid } });
                const video = document.createElement('video');
                video.controls = false;
                video.playsInline = true;
                video.preload = 'auto';
                video.src = MEDIA_BASE + res.url;
                this.q('media').appendChild(video);
                this.player = htmlPlayer(video);
                this.kind = 'html';
                this.mediaId = res.id;
                video.addEventListener('click', () => this.toggle());
                await new Promise(r => { video.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 8000); });
                this.afterPlayerReady();
                this.loadPeaks(res.id);
            } finally {
                clearInterval(timer);
                this.setLoading(false);
            }
        },

        async useFile(file) {
            this.localFile = file;
            this.source = { ...this.source, kind: 'file', file };
            const isVideo = /^video\//.test(file.type) || /\.(mp4|mov|mkv|avi|webm)$/i.test(file.name);
            const el = document.createElement(isVideo ? 'video' : 'audio');
            el.preload = 'auto';
            el.playsInline = true;
            if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
            this.objectUrl = URL.createObjectURL(file);
            el.src = this.objectUrl;
            const media = this.q('media');
            media.innerHTML = '';
            media.appendChild(el);
            if (!isVideo) media.classList.add('v3-audio-only');
            el.addEventListener('click', () => this.toggle());
            this.player = htmlPlayer(el);
            this.kind = 'file';
            await new Promise(r => { el.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 6000); });
            this.afterPlayerReady();
            this.peaksFromFile(file);
        },

        pickFile() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.mp4,.mov,.mkv,.avi,.webm,.mp3,.m4a,.wav,.ogg,.opus,.aac,.flac,.weba';
            input.onchange = () => { if (input.files[0]) this.useFile(input.files[0]); };
            input.click();
        },

        afterPlayerReady() {
            this.q('dur').textContent = fmtTime(this.duration());
            this.draw();
        },

        addWaveButton() {
            if (this.root.querySelector('[data-v="load-wave"]')) return;
            const btn = document.createElement('button');
            btn.className = 'link-btn v3-wave-btn';
            btn.dataset.v = 'load-wave';
            btn.textContent = 'Mostrar forma de onda';
            btn.title = 'Baja el audio en segundo plano para dibujar el volumen (ayuda a cortar en los silencios)';
            this.q('timeline').parentNode.appendChild(btn);
        },

        async loadWaveformForYoutube() {
            const btn = this.root.querySelector('[data-v="load-wave"]');
            if (btn) { btn.disabled = true; btn.textContent = 'Preparando la forma de onda...'; }
            try {
                const res = await api('/media/prepare', { method: 'POST', body: { url: this.source.url } });
                await this.loadPeaks(res.id);
                btn?.remove();
            } catch (e) {
                if (btn) { btn.disabled = false; btn.textContent = 'Mostrar forma de onda'; }
                toast(e.message, 'error');
            }
        },

        async loadPeaks(mediaId) {
            try {
                const res = await api(`/media/${mediaId}/peaks`);
                this.peaks = res.peaks || [];
                this.draw();
            } catch { /* sin forma de onda: no es grave */ }
        },

        async peaksFromFile(file) {
            if (file.size > 150 * 1024 * 1024 || !window.AudioContext) return;   // muy grande para el navegador
            try {
                const ctx = new AudioContext();
                const audio = await ctx.decodeAudioData(await file.arrayBuffer());
                const data = audio.getChannelData(0);
                const buckets = 1600, step = Math.max(1, Math.floor(data.length / buckets));
                const peaks = [];
                for (let i = 0; i < data.length; i += step) {
                    let m = 0;
                    for (let j = i; j < Math.min(i + step, data.length); j += 8) m = Math.max(m, Math.abs(data[j]));
                    peaks.push(m);
                }
                const top = Math.max(...peaks) || 1;
                this.peaks = peaks.map(p => Math.round(p * 100 / top));
                ctx.close();
                this.draw();
            } catch { /* formato que el navegador no decodifica: sin forma de onda */ }
        },

        // ── Reproducción ──
        now() { return this.player ? this.player.time() : 0; },
        duration() {
            const d = this.player?.duration() || 0;
            const last = this.segments.length ? this.segments[this.segments.length - 1].end : 0;
            return d > 1 ? d : last;
        },
        seek(t) {
            if (!this.player) return;
            this.player.seek(t);
            this.userScrollUntil = 0;
            this.draw();
        },
        skip(d) { this.seek(this.now() + d); },
        toggle() {
            if (!this.player) { this.open(); return; }
            if (this.player.paused()) this.player.play(); else this.player.pause();
        },
        preview() {
            if (this.selIn == null || this.selOut == null) { toast('Primero marcá el inicio y el fin del tramo', 'info'); return; }
            this.previewStop = this.selOut;
            this.seek(this.selIn);
            this.player.play();
        },

        loop() {
            cancelAnimationFrame(this.raf);
            let last = 0;
            const step = (ts) => {
                this.raf = requestAnimationFrame(step);
                if (!this.root || !this.player || ts - last < 120) return;
                last = ts;
                const t = this.now();
                if (this.previewStop != null && t >= this.previewStop) { this.player.pause(); this.previewStop = null; }
                this.q('now').textContent = fmtTime(t);
                const playIcon = this.q('play').querySelector('.material-symbols-outlined');
                const icon = this.player.paused() ? 'play_arrow' : 'pause';
                if (playIcon.textContent !== icon) playIcon.textContent = icon;
                this.highlight(t);
                this.draw();
            };
            this.raf = requestAnimationFrame(step);
        },

        // ── Texto sincronizado ──
        renderList() {
            const tr = this.translations;
            this.q('list').classList.toggle('v3-bilingual', !!tr);
            this.q('list').innerHTML = this.segments.map((s, i) => {
                const text = s.words?.length
                    ? s.words.map(w => `<span class="v3-w" data-ws="${w.s}" data-we="${w.e}">${esc(w.w)}</span>`).join(' ')
                    : esc(s.text);
                return `<div class="v3-seg" data-i="${i}">
                    <span class="v3-seg-time">${fmtTime(s.start)}</span>
                    <span class="v3-seg-text">${text}</span>
                    ${tr ? `<span class="v3-seg-tr">${esc(tr[i] || '')}</span>` : ''}
                </div>`;
            }).join('');
            this.activeIdx = -1;
            this.markSelection();
            if (this.q('search').value) this.search(this.q('search').value);
        },

        findIndex(t) {
            let lo = 0, hi = this.segments.length - 1, ans = -1;
            while (lo <= hi) {
                const mid = (lo + hi) >> 1;
                if (this.segments[mid].start <= t + 0.05) { ans = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return ans;
        },

        highlight(t) {
            const idx = this.findIndex(t);
            const list = this.q('list');
            if (idx !== this.activeIdx) {
                list.querySelector('.v3-seg.active')?.classList.remove('active');
                const el = list.querySelector(`[data-i="${idx}"]`);
                if (el) {
                    el.classList.add('active');
                    if (this.q('follow').checked && Date.now() > this.userScrollUntil && !this.player.paused()) {
                        const top = el.offsetTop - list.offsetTop - list.clientHeight / 3;
                        list.scrollTo({ top, behavior: 'smooth' });
                    }
                }
                this.activeIdx = idx;
            }
            const seg = this.segments[idx];
            const prev = list.querySelector('.v3-w.on');
            if (seg?.words?.length) {
                const el = list.querySelector(`[data-i="${idx}"]`);
                let on = null;
                el?.querySelectorAll('.v3-w').forEach(w => { if (parseFloat(w.dataset.ws) <= t + 0.05) on = w; });
                if (on !== prev) { prev?.classList.remove('on'); on?.classList.add('on'); }
            } else prev?.classList.remove('on');
        },

        // ── Selección del tramo ──
        setIn(t) {
            if (t == null || isNaN(t)) { this.syncInputs(); return; }
            this.selIn = Math.max(0, t);
            if (this.selOut != null && this.selOut <= this.selIn) this.selOut = null;
            this.syncInputs(); this.draw(); this.markSelection();
        },
        setOut(t) {
            if (t == null || isNaN(t)) { this.syncInputs(); return; }
            this.selOut = t;
            if (this.selIn != null && this.selIn >= this.selOut) this.selIn = null;
            this.syncInputs(); this.draw(); this.markSelection();
        },
        syncInputs() {
            this.q('in').value = this.selIn == null ? '' : fmtTime(this.selIn, true);
            this.q('out').value = this.selOut == null ? '' : fmtTime(this.selOut, true);
            const status = this.q('cut-status');
            status.textContent = (this.selIn != null && this.selOut != null) ? `Tramo de ${fmtTime(this.selOut - this.selIn)}` : '';
            // Se mantiene sincronizado con el recorte del panel de descarga (versión anterior)
            const a = document.getElementById('clip-start'), b = document.getElementById('clip-end');
            if (a) a.value = this.selIn == null ? '' : fmtTime(this.selIn);
            if (b) b.value = this.selOut == null ? '' : fmtTime(Math.ceil(this.selOut));
        },
        markSelection() {
            const list = this.q('list');
            if (!list) return;
            list.querySelectorAll('.v3-seg').forEach(el => {
                const s = this.segments[Number(el.dataset.i)];
                const inside = this.selIn != null && this.selOut != null && overlap(s, this.selIn, this.selOut) > 0.3;
                el.classList.toggle('in-cut', inside);
            });
        },

        selectionFromText() {
            const sel = window.getSelection();
            if (!sel || sel.isCollapsed || !sel.rangeCount) return;
            const list = this.q('list');
            const range = sel.getRangeAt(0);
            if (!list.contains(range.commonAncestorContainer)) return;
            const pick = (node, isEnd) => {
                const el = node.nodeType === 1 ? node : node.parentElement;
                const w = el?.closest('[data-ws]');
                if (w) return isEnd ? parseFloat(w.dataset.we) : parseFloat(w.dataset.ws);
                const seg = el?.closest('[data-i]');
                if (seg) { const s = this.segments[Number(seg.dataset.i)]; return isEnd ? s.end : s.start; }
                return null;
            };
            let a = pick(range.startContainer, false), b = pick(range.endContainer, true);
            if (a == null || b == null) return;
            if (b < a) [a, b] = [b, a];
            if (b - a < 0.3) return;
            this.selIn = Math.max(0, a - 0.15);
            this.selOut = b + 0.25;
            this.syncInputs(); this.draw(); this.markSelection();
            toast(`Tramo marcado: ${fmtTime(this.selIn)} → ${fmtTime(this.selOut)}`, 'success', 2200);
        },

        selectedText() {
            if (this.selIn == null || this.selOut == null) return '';
            const parts = [];
            for (const s of this.segments) {
                if (overlap(s, this.selIn, this.selOut) <= 0.3) continue;
                if (s.words?.length) parts.push(s.words.filter(w => (w.s + w.e) / 2 > this.selIn && (w.s + w.e) / 2 < this.selOut).map(w => w.w).join(' '));
                else parts.push(s.text);
            }
            return parts.join(' ').replace(/\s+/g, ' ').trim();
        },

        copySelection() {
            const text = this.selectedText();
            if (!text) { toast('Marcá un tramo primero (seleccioná el texto o usá Inicio / Fin)', 'info'); return; }
            navigator.clipboard.writeText(formatQuote(text, { start: this.selIn }));
            toast('Cita copiada con su atribución y enlace', 'success');
        },

        // ── Línea de tiempo (forma de onda + tramo + cursor) ──
        resizeCanvas() {
            const c = this.q('timeline');
            const w = c.clientWidth || 600;
            const dpr = window.devicePixelRatio || 1;
            c.width = Math.round(w * dpr);
            c.height = Math.round(64 * dpr);
            this.draw();
        },

        draw() {
            const c = this.q?.('timeline');
            if (!c || !c.width) return;
            const ctx = c.getContext('2d');
            const W = c.width, H = c.height, dur = this.duration() || 1;
            const css = getComputedStyle(document.documentElement);
            const primary = `rgb(${css.getPropertyValue('--c-primary').trim().replace(/ /g, ',')})`;
            const dim = `rgba(${css.getPropertyValue('--s500').trim().replace(/ /g, ',')},0.45)`;
            ctx.clearRect(0, 0, W, H);
            // Marcas de frases (siempre) y forma de onda (si hay)
            if (this.peaks.length) {
                const n = this.peaks.length, bw = W / n;
                ctx.fillStyle = dim;
                for (let i = 0; i < n; i++) {
                    const h = Math.max(1, this.peaks[i] / 100 * (H - 8));
                    ctx.fillRect(i * bw, (H - h) / 2, Math.max(1, bw - 0.5), h);
                }
            } else {
                ctx.fillStyle = dim;
                for (const s of this.segments) {
                    const x = s.start / dur * W, w = Math.max(1, (s.end - s.start) / dur * W - 1);
                    ctx.fillRect(x, H / 2 - 5, w, 10);
                }
            }
            if (this.selIn != null || this.selOut != null) {
                const a = (this.selIn ?? 0) / dur * W, b = (this.selOut ?? dur) / dur * W;
                ctx.fillStyle = `rgba(${css.getPropertyValue('--c-primary').trim().replace(/ /g, ',')},0.22)`;
                ctx.fillRect(a, 0, b - a, H);
                ctx.fillStyle = primary;
                if (this.selIn != null) ctx.fillRect(a - 1, 0, 3, H);
                if (this.selOut != null) ctx.fillRect(b - 1, 0, 3, H);
            }
            const x = this.now() / dur * W;
            ctx.fillStyle = primary;
            ctx.fillRect(x - 1, 0, 2 * (window.devicePixelRatio || 1), H);
        },

        bindTimeline() {
            const c = this.q('timeline');
            const tAt = (e) => {
                const r = c.getBoundingClientRect();
                return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * this.duration();
            };
            let dragging = null, startT = 0, moved = false;
            c.addEventListener('pointerdown', (e) => {
                if (!this.player) { this.open(); return; }
                const t = tAt(e), dur = this.duration(), tol = dur * 0.012;
                moved = false;
                startT = t;
                if (this.selIn != null && Math.abs(t - this.selIn) < tol) dragging = 'in';
                else if (this.selOut != null && Math.abs(t - this.selOut) < tol) dragging = 'out';
                else dragging = 'new';
                c.setPointerCapture(e.pointerId);
            });
            c.addEventListener('pointermove', (e) => {
                const t = tAt(e);
                const dur = this.duration(), tol = dur * 0.012;
                c.style.cursor = (this.selIn != null && Math.abs(t - this.selIn) < tol) ||
                    (this.selOut != null && Math.abs(t - this.selOut) < tol) ? 'ew-resize' : 'pointer';
                if (!dragging) return;
                if (Math.abs(t - startT) > dur * 0.004) moved = true;
                if (!moved) return;
                if (dragging === 'in') this.selIn = Math.min(t, (this.selOut ?? dur) - 0.2);
                else if (dragging === 'out') this.selOut = Math.max(t, (this.selIn ?? 0) + 0.2);
                else { this.selIn = Math.min(startT, t); this.selOut = Math.max(startT, t); }
                this.syncInputs(); this.draw();
            });
            c.addEventListener('pointerup', (e) => {
                if (!dragging) return;
                if (!moved) this.seek(tAt(e));
                else this.markSelection();
                dragging = null;
            });
            window.addEventListener('resize', () => this.root && this.resizeCanvas());
        },

        // ── Recorte ──
        async downloadClip() {
            if (this.selIn == null || this.selOut == null) { toast('Marcá el inicio y el fin del tramo a recortar', 'info'); return; }
            const btn = this.q('download');
            const status = this.q('cut-status');
            const burn = this.q('subs').checked, vertical = this.q('vertical').checked;
            const segments = burn ? this.segments.filter(s => overlap(s, this.selIn, this.selOut) > 0.3)
                .map(s => ({ start: s.start, end: s.end, text: s.text })) : [];
            btn.disabled = true;
            const progressUid = uid();
            let timer = null;
            try {
                let response;
                if (this.source.kind === 'file') {
                    const file = this.source.file || this.localFile;
                    if (!file) throw new Error('Elegí el archivo de nuevo para poder recortarlo.');
                    status.textContent = 'Recortando...';
                    const form = new FormData();
                    form.append('file', file);
                    form.append('start', String(this.selIn));
                    form.append('end', String(this.selOut));
                    form.append('burn_subs', String(burn));
                    form.append('vertical', String(vertical));
                    form.append('segments', JSON.stringify(segments));
                    response = await api('/clip-file', { method: 'POST', form });
                } else {
                    timer = setInterval(async () => {
                        try { const p = await api(`/progress/${progressUid}`); if (p.text) status.textContent = p.text; } catch { /* sigue */ }
                    }, 900);
                    status.textContent = 'Descargando el tramo...';
                    response = await api('/download', { method: 'POST', body: {
                        url: this.source.url, format_id: window.Clipa?.getFormat?.() || 'best', quality: window.Clipa?.getQuality?.(),
                        start_time: this.selIn.toFixed(2), end_time: this.selOut.toFixed(2), uid: progressUid,
                        burn_subs: burn, vertical, segments } });
                }
                const blob = await response.blob();
                const title = (window.Clipa?.getMeta?.().title || 'recorte').replace(/[\\/:*?"<>|]+/g, ' ').slice(0, 40).trim();
                downloadBlob(blob, filenameFrom(response, `${title}_${fmtTime(this.selIn).replace(/:/g, '-')}.mp4`));
                status.textContent = 'Recorte descargado';
                toast('Recorte listo', 'success');
            } catch (e) {
                status.textContent = '';
                toast(e.message, 'error', 7000);
            } finally {
                clearInterval(timer);
                btn.disabled = false;
            }
        },

        // ── Traducción frase por frase ──
        async translate(lang) {
            if (!lang) { this.translations = null; this.renderList(); return; }
            const sel = this.q('lang');
            sel.disabled = true;
            this.q('cut-status').textContent = 'Traduciendo...';
            try {
                const texts = this.segments.map(s => s.text);
                const out = [];
                for (let i = 0; i < texts.length; i += 400) {
                    const res = await api('/translate-segments', { method: 'POST', body: { texts: texts.slice(i, i + 400), target: lang } });
                    out.push(...res.texts);
                }
                this.translations = out;
                this.renderList();
            } catch (e) {
                sel.value = '';
                toast(e.message, 'error');
            } finally {
                sel.disabled = false;
                this.q('cut-status').textContent = '';
            }
        },

        // ── Búsqueda dentro de la transcripción ──
        search(query) {
            const list = this.q('list');
            list.querySelectorAll('.v3-hit').forEach(el => el.classList.remove('v3-hit', 'v3-hit-now'));
            this.searchHits = [];
            this.searchPos = -1;
            const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
            const q = norm(query.trim());
            const count = this.q('search-count');
            if (!q) { count.textContent = ''; return; }
            this.segments.forEach((s, i) => {
                const tr = this.translations?.[i] || '';
                if (norm(s.text).includes(q) || norm(tr).includes(q)) this.searchHits.push(i);
            });
            this.searchHits.forEach(i => list.querySelector(`[data-i="${i}"]`)?.classList.add('v3-hit'));
            count.textContent = this.searchHits.length ? `${this.searchHits.length}` : 'sin resultados';
        },

        nextHit(dir = 1) {
            if (!this.searchHits.length) return;
            const list = this.q('list');
            list.querySelector('.v3-hit-now')?.classList.remove('v3-hit-now');
            this.searchPos = (this.searchPos + dir + this.searchHits.length) % this.searchHits.length;
            const i = this.searchHits[this.searchPos];
            const el = list.querySelector(`[data-i="${i}"]`);
            el?.classList.add('v3-hit-now');
            if (el) list.scrollTo({ top: el.offsetTop - list.offsetTop - 40, behavior: 'smooth' });
            this.userScrollUntil = Date.now() + 4000;
            this.q('search-count').textContent = `${this.searchPos + 1} de ${this.searchHits.length}`;
            if (this.player) this.seek(this.segments[i].start);
        },
    };

    // ═════════════════════════════════════════════════════════════════════════════
    //  Interfaz: se monta cuando main.js avisa que arrancó
    // ═════════════════════════════════════════════════════════════════════════════

    // ── Texto original / corregido por la IA ──
    function mountRawToggle({ text, raw, segments }) {
        document.getElementById('v3-raw-toggle')?.remove();
        if (!raw || raw.replace(/\s+/g, ' ').trim() === String(text || '').replace(/\s+/g, ' ').trim()) return;
        const header = document.querySelector('#transcript-content > div');
        if (!header) return;
        const wrap = document.createElement('div');
        wrap.id = 'v3-raw-toggle';
        wrap.className = 'v3-raw-toggle';
        wrap.innerHTML = `
            <button class="active" data-raw="0" title="Con puntuación y párrafos corregidos por la IA">Corregido</button>
            <button data-raw="1" title="Tal como salió de la transcripción, antes de la corrección con IA">Original</button>`;
        header.appendChild(wrap);
        wrap.addEventListener('click', (e) => {
            const b = e.target.closest('[data-raw]');
            if (!b) return;
            wrap.querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
            const container = document.getElementById('transcript-text-container');
            if (!container) return;
            if (b.dataset.raw === '1') {
                container.innerHTML = `<p class="v3-raw-note"><span class="material-symbols-outlined">info</span>
                    Texto original, antes de la corrección de puntuación con IA. Usalo para verificar una cita palabra por palabra.</p>` +
                    raw.split(/\n\s*\n/).map(p => `<p class="mb-4">${esc(p.trim())}</p>`).join('');
            } else {
                container.innerHTML = window.Clipa.formatText(text, segments);
            }
        });
    }

    // ── Panel de trabajos ──
    function mountJobsPanel() {
        const topbar = document.querySelector('.topbar');
        const themeBtn = document.getElementById('theme-toggle-btn');
        if (!topbar || document.getElementById('v3-jobs-btn')) return;
        const btn = document.createElement('button');
        btn.id = 'v3-jobs-btn';
        btn.className = 'icon-btn v3-jobs-btn';
        btn.title = 'Trabajos en segundo plano';
        btn.setAttribute('aria-label', 'Trabajos en segundo plano');
        btn.innerHTML = '<span class="material-symbols-outlined">pending_actions</span><span class="v3-badge hidden" id="v3-jobs-badge"></span>';
        topbar.insertBefore(btn, themeBtn);

        const panel = document.createElement('div');
        panel.id = 'v3-jobs-panel';
        panel.className = 'v3-jobs-panel hidden';
        panel.innerHTML = `
            <div class="v3-jobs-head">
                <h3>Trabajos en segundo plano</h3>
                <button class="icon-btn-sm" data-j="close" aria-label="Cerrar"><span class="material-symbols-outlined">close</span></button>
            </div>
            <p class="v3-jobs-help">Pegá uno o varios enlaces (uno por línea). Se transcriben en el servidor aunque cierres esta pestaña, y quedan en el Historial.</p>
            <textarea class="field w-full" id="v3-jobs-input" rows="3" placeholder="https://www.youtube.com/watch?v=...&#10;https://www.instagram.com/reel/..."></textarea>
            <div class="v3-jobs-row">
                <select class="field" id="v3-jobs-lang" title="Idioma de la transcripción">
                    <option value="es">Español</option><option value="en">Inglés</option><option value="original">Idioma original</option>
                </select>
                <button class="btn-primary" data-j="add"><span class="material-symbols-outlined">playlist_add</span> Transcribir</button>
            </div>
            <div id="v3-jobs-list" class="v3-jobs-list"></div>`;
        document.body.appendChild(panel);

        const toggle = (open) => {
            panel.classList.toggle('hidden', !open);
            if (open) { jobs.refresh(); $('#v3-jobs-input').focus(); }
        };
        btn.addEventListener('click', () => toggle(panel.classList.contains('hidden')));
        document.addEventListener('click', (e) => {
            if (!panel.classList.contains('hidden') && !panel.contains(e.target) && !btn.contains(e.target) &&
                !e.target.closest('.v3-modal-backdrop')) toggle(false);
        });
        panel.addEventListener('click', async (e) => {
            const a = e.target.closest('[data-j]');
            if (!a) return;
            const act = a.dataset.j;
            if (act === 'close') toggle(false);
            if (act === 'add') {
                const urls = [...new Set(($('#v3-jobs-input').value.match(/https?:\/\/[^\s]+/g) || []))];
                if (!urls.length) { toast('Pegá al menos un enlace', 'info'); return; }
                a.disabled = true;
                let ok = 0;
                for (const url of urls) {
                    try { await jobs.create({ url, lang: $('#v3-jobs-lang').value }); ok++; } catch (err) { toast(`${url}: ${err.message}`, 'error'); }
                }
                a.disabled = false;
                if (ok) { $('#v3-jobs-input').value = ''; toast(`${ok} ${ok === 1 ? 'trabajo agregado' : 'trabajos agregados'}. Te aviso cuando terminen.`, 'success'); }
            }
            if (act === 'open') {
                toggle(false);
                window.Clipa.openHistory(Number(a.dataset.id));
            }
            if (act === 'dismiss') jobs.dismiss(a.dataset.id);
            if (act === 'stop') {
                a.disabled = true;
                await api(`/jobs/${a.dataset.id}/stop`, { method: 'POST' }).catch(err => toast(err.message, 'error'));
                jobs.poll();
            }
            if (act === 'retry') {
                const job = jobs.list.find(j => j.id === a.dataset.id);
                if (job) { await jobs.dismiss(job.id); jobs.create({ url: job.url, lang: job.lang, title: job.title }); }
            }
        });
        jobs.refresh().then(() => { if (jobs.list.some(j => j.status === 'running' || j.status === 'queued')) jobs.poll(); });
    }

    function renderJobsPanel() {
        const list = document.getElementById('v3-jobs-list');
        const badge = document.getElementById('v3-jobs-badge');
        const active = jobs.list.filter(j => j.status === 'queued' || j.status === 'running').length;
        if (badge) { badge.textContent = active; badge.classList.toggle('hidden', !active); }
        document.getElementById('v3-jobs-btn')?.classList.toggle('v3-busy', active > 0);
        if (!list) return;
        if (!jobs.list.length) { list.innerHTML = '<p class="v3-jobs-empty">No hay trabajos todavía.</p>'; return; }
        list.innerHTML = jobs.list.map(j => {
            const title = esc(j.title || j.url);
            const states = {
                queued: `<span class="v3-st">En cola</span>`,
                running: `<div class="progress-track v3-mini"><div style="width:${Number(j.progress) || 0}%"></div></div><span class="v3-st">${esc(j.text || 'Procesando...')}</span>`,
                done: j.warning ? `<span class="v3-st v3-warn">${esc(j.warning)}</span>` : `<span class="v3-st v3-ok">${j.kind === 'record' ? `Guardada${j.size_mb ? ` · ${esc(j.size_mb)} MB` : ''}` : 'Lista'}</span>`,
                error: `<span class="v3-st v3-err">${esc(j.error || 'Error')}</span>`,
            };
            const isRec = j.kind === 'record';
            let actions = '';
            if (isRec && j.status === 'running') actions = `<button class="link-btn v3-stop" data-j="stop" data-id="${esc(j.id)}"><span class="material-symbols-outlined text-base">stop_circle</span> Detener</button>`;
            else if (isRec && j.status === 'done') actions = (j.file ? `<a class="link-btn" href="${API}/record/${encodeURIComponent(j.id)}/file" download>Descargar</a>` : '')
                + (j.history_id ? ` <button class="link-btn" data-j="open" data-id="${Number(j.history_id)}">Abrir</button>` : '');
            else if (j.status === 'done') actions = `<button class="link-btn" data-j="open" data-id="${Number(j.history_id)}">Abrir</button>`;
            else if (j.status === 'error' && !isRec) actions = `<button class="link-btn" data-j="retry" data-id="${esc(j.id)}">Reintentar</button>`;
            const dismiss = (j.status === 'done' || j.status === 'error')
                ? `<button class="icon-btn-sm" data-j="dismiss" data-id="${esc(j.id)}" title="Quitar de la lista"><span class="material-symbols-outlined text-base">close</span></button>` : '';
            const icon = isRec ? '<span class="v3-rec-dot" title="Grabación de un vivo"></span>' : '';
            return `<div class="v3-job v3-job-${esc(j.status)}"><div class="v3-job-main"><p class="v3-job-title" title="${esc(j.url)}">${icon}${title}</p>${states[j.status] || ''}</div><div class="v3-job-actions">${actions}${dismiss}</div></div>`;
        }).join('');
    }

    // ── Aviso de cookies vencidas ──
    async function checkCookiesBanner() {
        try {
            const h = await api('/health');
            if (window.Clipa) window.Clipa.serverHasGroq = !!h.groq_server_key;
            if (!h.has_cookies) return;
            const last = Number(store.get('clipadsk_cookie_check') || 0);
            let valid = store.get('clipadsk_cookie_valid') !== '0';
            if (Date.now() - last > 12 * 3600 * 1000) {
                const r = await api('/health/cookies');
                valid = !!r.cookie_valid;
                store.set('clipadsk_cookie_check', String(Date.now()));
                store.set('clipadsk_cookie_valid', valid ? '1' : '0');
            }
            if (valid) return;
            const main = document.querySelector('.app-main');
            if (!main || document.getElementById('v3-cookie-banner')) return;
            const b = document.createElement('div');
            b.id = 'v3-cookie-banner';
            b.className = 'v3-banner';
            b.innerHTML = `<span class="material-symbols-outlined">cookie</span>
                <p><b>Las cookies de YouTube vencieron.</b> Algunas descargas van a fallar hasta que las renueves: exportalas de nuevo desde el navegador y reemplazá el archivo cookies.txt.</p>
                <a class="btn-ghost" href="setup.html">Cómo renovarlas</a>
                <button class="icon-btn-sm" aria-label="Cerrar aviso"><span class="material-symbols-outlined">close</span></button>`;
            b.querySelector('button').onclick = () => { b.remove(); store.set('clipadsk_cookie_check', String(Date.now())); };
            main.prepend(b);
        } catch { /* servidor apagado: el indicador de estado ya lo muestra */ }
    }

    // ── Arrastrar un archivo a cualquier parte de la ventana ──
    const VIDEO_RE = /\.(mp4|mov|avi|mkv|webm)$/i;
    const AUDIO_RE = /\.(ogg|opus|mp3|m4a|wav|aac|weba|flac)$/i;
    function mountGlobalDrop() {
        const overlay = document.createElement('div');
        overlay.className = 'v3-drop hidden';
        overlay.innerHTML = '<div><span class="material-symbols-outlined">upload_file</span><p>Soltá el archivo para transcribirlo</p><small>Audio (WhatsApp, grabaciones) o video</small></div>';
        document.body.appendChild(overlay);
        let depth = 0;
        const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
        window.addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; depth++; overlay.classList.remove('hidden'); });
        window.addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) overlay.classList.add('hidden'); });
        window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
        window.addEventListener('drop', (e) => {
            if (!hasFiles(e)) return;
            depth = 0;
            overlay.classList.add('hidden');
            if (e.target.closest?.('.dropzone')) return;   // las zonas propias ya lo manejan
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (!file) return;
            if (VIDEO_RE.test(file.name)) { window.Clipa.switchTab('video'); window.Clipa.processVideoFile(file); }
            else if (AUDIO_RE.test(file.name)) { window.Clipa.switchTab('whatsapp'); window.Clipa.processAudioFile(file); }
            else toast(`Formato no soportado: ${file.name}`, 'error');
        });
    }

    // ── Pegar un enlace = analizarlo ──
    function mountPasteToAnalyze() {
        const looksLikeUrl = (s) => /^https?:\/\/\S+$/i.test(String(s || '').trim());
        const url = document.getElementById('video-url');
        url?.addEventListener('paste', () => setTimeout(() => {
            if (looksLikeUrl(url.value)) document.getElementById('fetch-info-btn')?.click();
        }, 0));
        const home = document.getElementById('home-url-input');
        home?.addEventListener('paste', () => setTimeout(() => {
            if (looksLikeUrl(home.value)) document.getElementById('home-url-btn')?.click();
        }, 0));
    }

    // ── Atajos de teclado ──
    const SHORTCUTS = [
        ['Ctrl + Shift + C', 'Copiar la transcripción'],
        ['/', 'Buscar en el historial'],
        ['Barra espaciadora', 'Reproducir / pausar (visualizador abierto)'],
        ['J / L', 'Atrás / adelante 5 segundos'],
        ['I / O', 'Marcar inicio / fin del recorte'],
        ['P', 'Ver solo el tramo marcado'],
        ['?', 'Ver esta lista'],
    ];
    function mountShortcuts() {
        document.addEventListener('keydown', (e) => {
            const t = e.target;
            const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
            if (document.querySelector('.v3-modal-backdrop')) return;
            if (e.ctrlKey && e.shiftKey && (e.key === 'C' || e.key === 'c')) {
                const btn = document.getElementById('copy-transcript-btn');
                if (btn && !document.getElementById('transcript-section')?.classList.contains('hidden')) { e.preventDefault(); btn.click(); }
                return;
            }
            if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
            if (e.key === '/') { e.preventDefault(); document.getElementById('global-search-input')?.focus(); return; }
            if (e.key === '?') {
                e.preventDefault();
                dialog({ title: 'Atajos de teclado', html: true, cancelText: '', okText: 'Cerrar',
                    message: `<table class="v3-keys">${SHORTCUTS.map(([k, d]) => `<tr><td><kbd>${esc(k)}</kbd></td><td>${esc(d)}</td></tr>`).join('')}</table>` });
                return;
            }
            if (!viewer.isOpen()) return;
            const key = e.key.toLowerCase();
            const map = { ' ': () => viewer.toggle(), j: () => viewer.skip(-5), l: () => viewer.skip(5),
                i: () => viewer.setIn(viewer.now()), o: () => viewer.setOut(viewer.now()), p: () => viewer.preview() };
            if (map[key]) { e.preventDefault(); map[key](); }
        });
    }

    // ── Estimación en la tarjeta del video ──
    function showEstimate(info) {
        document.getElementById('v3-estimate')?.remove();
        const text = estimateTranscription(info);
        const btn = document.getElementById('show-transcript-btn');
        if (!text || !btn) return;
        const p = document.createElement('p');
        p.id = 'v3-estimate';
        p.className = 'v3-estimate';
        p.innerHTML = `<span class="material-symbols-outlined">schedule</span> Transcribir tarda ${esc(text)}.`;
        btn.closest('.grid')?.insertAdjacentElement('afterend', p);
    }


    // ─── Galería de carruseles de Instagram ──────────────────────────────────────
    const gallery = (() => {
        let info = null;
        let selected = new Set();
        let lightboxIndex = -1;

        const thumbUrl = (t) => (t && t.startsWith('/') ? MEDIA_BASE + t : t || '');

        function setCardMode(isCarousel) {
            const card = document.getElementById('video-info-card');
            if (!card) return;
            card.classList.toggle('v3-is-carousel', isCarousel);
            const thumbBox = document.getElementById('video-thumbnail')?.parentElement;
            if (thumbBox) thumbBox.style.display = isCarousel ? 'none' : '';
            const trim = document.getElementById('clip-start')?.closest('.space-y-2');
            if (trim) trim.style.display = isCarousel ? 'none' : '';
            const btn = document.getElementById('download-btn');
            if (btn) {
                if (!btn.dataset.v3Label) btn.dataset.v3Label = btn.innerHTML;
                btn.innerHTML = isCarousel
                    ? '<span class="material-symbols-outlined">folder_zip</span> Descargar todo (.zip)'
                    : btn.dataset.v3Label;
            }
        }

        function unmount() {
            document.getElementById('v3-carousel')?.remove();
            closeLightbox();
            info = null;
            selected = new Set();
            setCardMode(false);
        }

        function mount(detail) {
            unmount();
            const items = detail?.carousel;
            if (!Array.isArray(items) || !items.length) return;
            info = detail;
            const card = document.getElementById('video-info-card');
            const body = card?.querySelector('.p-6');
            if (!body) return;
            const nVideos = items.filter(i => i.is_video).length;
            const what = nVideos ? `${items.length} archivos (${items.length - nVideos} fotos, ${nVideos} videos)` : `${items.length} fotos`;
            const wrap = document.createElement('div');
            wrap.id = 'v3-carousel';
            wrap.className = 'v3-carousel';
            wrap.innerHTML = `
                <div class="v3-carousel-head">
                    <div><strong>Carrusel</strong> <span class="v3-hint">· ${esc(what)}</span></div>
                    <button type="button" class="v3-link" data-act="toggle-all">Elegir todas</button>
                </div>
                <div class="v3-carousel-grid">
                    ${items.map(it => `
                        <div class="v3-cimg" data-i="${it.index}" tabindex="0" role="checkbox" aria-checked="false"
                             title="Clic para elegir · doble clic para verla grande">
                            ${it.thumb ? `<img src="${esc(thumbUrl(it.thumb))}" alt="Archivo ${it.index + 1}" loading="lazy" referrerpolicy="no-referrer">`
                                       : `<div class="v3-cimg-empty"><span class="material-symbols-outlined">movie</span></div>`}
                            <span class="v3-cimg-num">${it.index + 1}</span>
                            ${it.is_video ? '<span class="v3-cimg-video material-symbols-outlined">play_circle</span>' : ''}
                            <span class="v3-cimg-check material-symbols-outlined">check</span>
                            <div class="v3-cimg-tools">
                                <button type="button" data-act="zoom" title="Ver grande"><span class="material-symbols-outlined">zoom_in</span></button>
                                <button type="button" data-act="one" title="Descargar solo esta"><span class="material-symbols-outlined">download</span></button>
                            </div>
                        </div>`).join('')}
                </div>
                <button type="button" class="btn-soft w-full v3-carousel-dl" data-act="selected" disabled>
                    <span class="material-symbols-outlined">download</span> <span class="v3-carousel-dl-label">Elegí las fotos que querés bajar</span>
                </button>`;
            const first = body.firstElementChild;
            first ? first.insertAdjacentElement('afterend', wrap) : body.prepend(wrap);
            setCardMode(true);

            wrap.addEventListener('click', (e) => {
                const btn = e.target.closest('button[data-act]');
                const tile = e.target.closest('.v3-cimg');
                if (btn) {
                    e.stopPropagation();
                    const act = btn.dataset.act;
                    if (act === 'toggle-all') toggleAll();
                    else if (act === 'selected') download([...selected], btn);
                    else if (act === 'zoom' && tile) openLightbox(+tile.dataset.i);
                    else if (act === 'one' && tile) download([+tile.dataset.i], btn);
                    return;
                }
                if (tile) toggle(+tile.dataset.i);
            });
            wrap.addEventListener('dblclick', (e) => {
                const tile = e.target.closest('.v3-cimg');
                if (tile) { toggle(+tile.dataset.i); openLightbox(+tile.dataset.i); }
            });
            wrap.addEventListener('keydown', (e) => {
                const tile = e.target.closest('.v3-cimg');
                if (!tile) return;
                if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); e.key === ' ' ? toggle(+tile.dataset.i) : openLightbox(+tile.dataset.i); }
            });
            refresh();
        }

        function toggle(i) {
            selected.has(i) ? selected.delete(i) : selected.add(i);
            refresh();
        }

        function toggleAll() {
            const all = info?.carousel || [];
            selected = selected.size === all.length ? new Set() : new Set(all.map(i => i.index));
            refresh();
        }

        function refresh() {
            const wrap = document.getElementById('v3-carousel');
            if (!wrap || !info) return;
            wrap.querySelectorAll('.v3-cimg').forEach(t => {
                const on = selected.has(+t.dataset.i);
                t.classList.toggle('selected', on);
                t.setAttribute('aria-checked', on ? 'true' : 'false');
            });
            const n = selected.size, total = info.carousel.length;
            const btn = wrap.querySelector('[data-act="selected"]');
            btn.disabled = n === 0;
            wrap.querySelector('.v3-carousel-dl-label').textContent =
                n === 0 ? 'Elegí las fotos que querés bajar'
                : n === 1 ? 'Descargar la elegida'
                : `Descargar las ${n} elegidas (.zip)`;
            wrap.querySelector('[data-act="toggle-all"]').textContent = n === total ? 'Quitar todas' : 'Elegir todas';
        }

        async function download(indexes, btn) {
            if (!indexes.length || !info) return;
            const old = btn?.innerHTML;
            if (btn) { btn.disabled = true; btn.innerHTML = '<span class="v3-spinner v3-spinner-sm"></span>'; }
            try {
                const r = await api('/download', { method: 'POST', body: { url: info.url, format_id: 'carousel_images', items: indexes.sort((a, b) => a - b) } });
                const blob = await r.blob();
                downloadBlob(blob, filenameFrom(r, indexes.length === 1 ? 'carrusel.jpg' : 'carrusel.zip'));
                toast(indexes.length === 1 ? 'Archivo descargado' : `${indexes.length} archivos descargados en un .zip`, 'success');
            } catch (err) {
                toast(err.message || 'No se pudo descargar', 'error');
            } finally {
                if (btn) { btn.innerHTML = old; btn.disabled = false; }
                refresh();
            }
        }

        function openLightbox(i) {
            const items = info?.carousel || [];
            const it = items[i];
            if (!it) return;
            lightboxIndex = i;
            let box = document.getElementById('v3-lightbox');
            if (!box) {
                box = document.createElement('div');
                box.id = 'v3-lightbox';
                box.className = 'v3-modal-backdrop v3-lightbox';
                box.innerHTML = `
                    <button type="button" class="v3-lb-nav v3-lb-prev" data-act="prev" title="Anterior (←)"><span class="material-symbols-outlined">chevron_left</span></button>
                    <figure class="v3-lb-figure"><div class="v3-lb-media"></div>
                        <figcaption class="v3-lb-bar">
                            <span class="v3-lb-count"></span>
                            <label class="v3-check"><input type="checkbox" data-act="pick"> Elegida</label>
                            <button type="button" class="btn-primary" data-act="one"><span class="material-symbols-outlined">download</span> Descargar esta</button>
                            <button type="button" class="btn-ghost" data-act="close">Cerrar</button>
                        </figcaption></figure>
                    <button type="button" class="v3-lb-nav v3-lb-next" data-act="next" title="Siguiente (→)"><span class="material-symbols-outlined">chevron_right</span></button>`;
                box.addEventListener('click', (e) => {
                    const act = e.target.closest('[data-act]')?.dataset.act;
                    if (e.target === box || act === 'close') closeLightbox();
                    else if (act === 'prev') step(-1);
                    else if (act === 'next') step(1);
                    else if (act === 'one') download([lightboxIndex], e.target.closest('button'));
                });
                box.querySelector('[data-act="pick"]').addEventListener('change', () => { toggle(lightboxIndex); });
                document.addEventListener('keydown', onLightboxKey, true);
                document.body.appendChild(box);
            }
            const media = box.querySelector('.v3-lb-media');
            media.innerHTML = it.thumb
                ? `<img src="${esc(thumbUrl(it.thumb))}" alt="Archivo ${i + 1}" referrerpolicy="no-referrer">${it.is_video ? '<span class="v3-lb-video">Video · se ve la portada; al descargar baja el video completo</span>' : ''}`
                : '<div class="v3-cimg-empty"><span class="material-symbols-outlined">movie</span><p>Video sin vista previa</p></div>';
            box.querySelector('.v3-lb-count').textContent = `${i + 1} de ${items.length}`;
            box.querySelector('[data-act="pick"]').checked = selected.has(i);
            box.querySelector('.v3-lb-prev').disabled = i === 0;
            box.querySelector('.v3-lb-next').disabled = i === items.length - 1;
        }

        function step(d) {
            const n = info?.carousel?.length || 0;
            const next = lightboxIndex + d;
            if (next >= 0 && next < n) openLightbox(next);
        }

        function onLightboxKey(e) {
            if (!document.getElementById('v3-lightbox')) return;
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeLightbox(); }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); step(-1); }
            else if (e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); step(1); }
            else if (e.key === ' ') { e.preventDefault(); e.stopPropagation(); toggle(lightboxIndex); openLightbox(lightboxIndex); }
        }

        function closeLightbox() {
            document.getElementById('v3-lightbox')?.remove();
            document.removeEventListener('keydown', onLightboxKey, true);
            lightboxIndex = -1;
        }

        return { mount, unmount, selected: () => [...selected] };
    })();


    // ─── Motor de descarga: ajustes, listas, vivos, comentarios y canales vigilados ──
    const motor = (() => {
        let settings = null;
        let lastEvent = Number(store.get('clipadsk_watch_last') || 0);
        let eventsTimer = null;

        async function loadSettings() {
            try { settings = await api('/settings'); } catch { settings = settings || {}; }
            return settings;
        }

        async function saveSetting(patch) {
            try {
                settings = await api('/settings', { method: 'PUT', body: patch });
                toast('Guardado', 'success', 1500);
            } catch (err) { toast(err.message, 'error'); }
            renderSettingsCard();
            startEventsPolling();
            return settings;
        }

        // ── Tarjeta en Configuración ──
        function mountSettingsCard() {
            const section = document.getElementById('config-section');
            if (!section || document.getElementById('v3-motor-card')) return;
            const card = document.createElement('div');
            card.id = 'v3-motor-card';
            card.className = 'glass card space-y-3 v3-motor-card';
            section.insertBefore(card, section.children[2] || null);
            card.addEventListener('change', onSettingsChange);
            card.addEventListener('click', onSettingsClick);
            card.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && e.target.id === 'v3-watch-url') { e.preventDefault(); addWatch(); }
            });
            renderSettingsCard();
        }

        function renderSettingsCard() {
            const card = document.getElementById('v3-motor-card');
            if (!card || !settings) return;
            const st = settings;
            const sw = (key, label, help) => `
                <label class="v3-switch-row">
                    <span><b>${label}</b><small>${help}</small></span>
                    <input type="checkbox" class="v3-switch" data-s="${key}" ${st[key] ? 'checked' : ''}>
                </label>`;
            const opt = (v, t, cur) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${t}</option>`;
            card.innerHTML = `
                <div class="flex items-center gap-3">
                    <span class="quick-icon bg-primary/10 text-primary"><span class="material-symbols-outlined">tune</span></span>
                    <h3 class="font-semibold text-white">Funciones extra</h3>
                </div>
                <div class="v3-set-block">
                    <p class="v3-set-title">Subtítulos de YouTube</p>
                    <p class="v3-set-help">Si el video ya tiene subtítulos, el texto sale al instante y sin gastar Groq. Los automáticos tienen más errores que la transcripción.</p>
                    <select class="field w-full" data-s="subtitles_mode">
                        ${opt('auto', 'Usarlos siempre que haya (más rápido)', st.subtitles_mode)}
                        ${opt('manual', 'Solo los que cargó el autor (los automáticos no)', st.subtitles_mode)}
                        ${opt('never', 'Nunca: transcribir siempre (más preciso)', st.subtitles_mode)}
                    </select>
                </div>
                ${sw('comments_enabled', 'Comentarios de YouTube', 'Agrega el botón "Comentarios" al analizar un video: los más votados o los más nuevos, para leer o bajar en .txt.')}
                <div class="v3-set-block">
                    ${sw('watch_enabled', 'Vigilar canales', 'Avisa cuando un canal o una lista sube un video nuevo. Funciona mientras Clipadsk esté abierto en la PC.')}
                    <div class="v3-watch ${st.watch_enabled ? '' : 'v3-dim'}">
                        <div class="v3-watch-add">
                            <input id="v3-watch-url" class="field flex-1" placeholder="https://www.youtube.com/@canal" autocomplete="off">
                            <button class="btn-soft" data-a="add-watch"><span class="material-symbols-outlined">add</span> Vigilar</button>
                        </div>
                        <ul id="v3-watch-list" class="v3-watch-list"><li class="v3-hint">Cargando...</li></ul>
                        <div class="v3-watch-opts">
                            <label>Revisar cada
                                <select class="field" data-s="watch_interval_min">
                                    ${[15, 30, 60, 180, 720].map(m => opt(m, m < 60 ? `${m} min` : `${m / 60} h`, st.watch_interval_min)).join('')}
                                </select>
                            </label>
                            <button class="link-btn" data-a="check-now"><span class="material-symbols-outlined text-base">refresh</span> Revisar ahora</button>
                        </div>
                        ${sw('watch_auto_transcribe', 'Transcribir solo', 'Cada video nuevo se transcribe y queda en el Historial (usa la key de Groq del .env).')}
                        ${sw('windows_toasts', 'Aviso de Windows', 'Además del aviso del navegador, muestra una notificación de Windows aunque la pestaña esté cerrada.')}
                        <button class="link-btn" data-a="test-notif"><span class="material-symbols-outlined text-base">notifications</span> Permitir y probar avisos</button>
                    </div>
                </div>
                <div class="v3-set-block">
                    <p class="v3-set-title">Glosario de nombres propios</p>
                    <p class="v3-set-help">Un nombre por línea. Se le pasa a Whisper y a la limpieza con IA para que los escriba bien. Para corregir un error fijo: <code>Yemini = Gemini</code> (varias formas: <code>Cloud | Clod = Claude</code>).</p>
                    <textarea class="field w-full v3-glossary" data-s="glossary" rows="6" spellcheck="false" placeholder="Anthropic&#10;Yemini = Gemini&#10;Cloud = Claude">${esc(st.glossary || '')}</textarea>
                </div>
                <div class="v3-set-block">
                    <p class="v3-set-title">Grabación de vivos</p>
                    <label class="v3-watch-opts">Cortar sola después de
                        <select class="field" data-s="record_max_hours">
                            ${[1, 2, 4, 6, 12].map(h => opt(h, `${h} h`, st.record_max_hours)).join('')}
                        </select>
                    </label>
                </div>`;
            loadWatches();
        }

        async function onSettingsChange(e) {
            const key = e.target.dataset.s;
            if (!key) return;
            const value = e.target.type === 'checkbox' ? e.target.checked
                : (['watch_interval_min', 'record_max_hours'].includes(key) ? Number(e.target.value) : e.target.value);
            if (key === 'watch_enabled' && value) askNotificationPermission();
            await saveSetting({ [key]: value });
        }

        async function onSettingsClick(e) {
            const a = e.target.closest('[data-a]');
            if (!a) return;
            if (a.dataset.a === 'add-watch') addWatch();
            if (a.dataset.a === 'del-watch') {
                if (!await confirmDialog('¿Dejar de vigilar este canal?', { okText: 'Dejar de vigilar' })) return;
                const res = await api(`/watch/${a.dataset.id}`, { method: 'DELETE' }).catch(err => toast(err.message, 'error'));
                if (res) renderWatches(res.watches);
            }
            if (a.dataset.a === 'check-now') {
                a.disabled = true;
                try {
                    const res = await api('/watch/check', { method: 'POST' });
                    renderWatches(res.watches);
                    toast(res.new ? `${res.new} video(s) nuevo(s)` : 'No hay videos nuevos', res.new ? 'success' : 'info');
                    pollEvents();
                } catch (err) { toast(err.message, 'error'); }
                a.disabled = false;
            }
            if (a.dataset.a === 'test-notif') {
                if ('Notification' in window && Notification.permission !== 'granted') await Notification.requestPermission().catch(() => {});
                showNotification('Clipadsk', 'Así se van a ver los avisos de videos nuevos.');
            }
        }

        async function addWatch() {
            const input = document.getElementById('v3-watch-url');
            const url = input?.value.trim();
            if (!url) return;
            const btn = document.querySelector('[data-a="add-watch"]');
            if (btn) btn.disabled = true;
            try {
                const res = await api('/watch', { method: 'POST', body: { url } });
                input.value = '';
                renderWatches(res.watches);
                toast(`Vigilando: ${res.title}`, 'success');
                if (!settings.watch_enabled) await saveSetting({ watch_enabled: true });
            } catch (err) { toast(err.message, 'error'); }
            if (btn) btn.disabled = false;
        }

        async function loadWatches() {
            try { renderWatches((await api('/watch')).watches); } catch { renderWatches([]); }
        }

        function renderWatches(list) {
            const ul = document.getElementById('v3-watch-list');
            if (!ul) return;
            if (!list?.length) { ul.innerHTML = '<li class="v3-hint">Todavía no vigilás ningún canal.</li>'; return; }
            ul.innerHTML = list.map(w => {
                const when = w.last_check ? new Date(w.last_check * 1000).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'sin revisar';
                return `<li><span class="material-symbols-outlined">smart_display</span>
                    <div><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.title)}</a>
                    <small>${w.last_error ? `<span class="v3-err">${esc(w.last_error)}</span>` : `Última revisión: ${esc(when)}`}</small></div>
                    <button class="icon-btn-sm" data-a="del-watch" data-id="${Number(w.id)}" title="Dejar de vigilar"><span class="material-symbols-outlined text-base">close</span></button></li>`;
            }).join('');
        }

        // ── Avisos de videos nuevos ──
        function showNotification(title, body, onClick) {
            toast(`${title}: ${body}`, 'info', 8000);
            if ('Notification' in window && Notification.permission === 'granted') {
                try {
                    const n = new Notification(title, { body, icon: 'icon.svg' });
                    n.onclick = () => { window.focus(); onClick?.(); n.close(); };
                } catch { /* sin notificaciones del sistema */ }
            }
        }

        async function pollEvents() {
            try {
                const { events } = await api(`/watch/events?after=${lastEvent}`);
                const fresh = (events || []).filter(e => e.id > lastEvent).reverse();
                if (!lastEvent && fresh.length) {
                    // primera vez en este navegador: solo tomar nota, no avisar de lo viejo
                    lastEvent = fresh[fresh.length - 1].id;
                } else {
                    for (const ev of fresh) {
                        showNotification(`Video nuevo de ${ev.channel || 'un canal vigilado'}`, ev.title || ev.url, () => {
                            window.Clipa?.switchTab('link');
                            const input = document.getElementById('video-url');
                            if (input) { input.value = ev.url; document.getElementById('fetch-info-btn')?.click(); }
                        });
                        if (ev.job_id) jobs.poll();
                        lastEvent = Math.max(lastEvent, ev.id);
                    }
                }
                store.set('clipadsk_watch_last', String(lastEvent));
            } catch { /* servidor apagado */ }
        }

        function startEventsPolling() {
            clearInterval(eventsTimer);
            eventsTimer = null;
            if (!settings?.watch_enabled) return;
            pollEvents();
            eventsTimer = setInterval(pollEvents, 60000);
        }

        // ── Panel según lo que se pegó: lista, vivo, comentarios ──
        function clearInfoExtras() {
            document.getElementById('v3-list')?.remove();
            document.getElementById('v3-live')?.remove();
            document.getElementById('v3-comments-btn')?.remove();
            document.getElementById('v3-comments')?.remove();
            const card = document.getElementById('video-info-card');
            card?.classList.remove('v3-is-list');
            const trim = document.getElementById('clip-start')?.closest('.space-y-2');
            const fmt = document.getElementById('format-select')?.closest('.space-y-2');
            const dl = document.getElementById('download-btn');
            if (!card?.classList.contains('v3-is-carousel')) { if (trim) trim.style.display = ''; }
            if (fmt) fmt.style.display = '';
            if (dl) dl.style.display = '';
        }

        function onVideoInfo(info) {
            clearInfoExtras();
            const body = document.querySelector('#video-info-card .p-6');
            if (!body) return;
            if (Array.isArray(info.playlist) && info.playlist.length) mountList(info, body);
            else if (info.is_live) mountLive(info, body);
            if (settings?.comments_enabled && !info.playlist && /youtu\.?be/.test(info.url || '')) mountCommentsButton(info, body);
        }

        function mountList(info, body) {
            const card = document.getElementById('video-info-card');
            card.classList.add('v3-is-list');
            ['clip-start', 'format-select'].forEach(id => {
                const el = document.getElementById(id)?.closest('.space-y-2');
                if (el) el.style.display = 'none';
            });
            const dl = document.getElementById('download-btn');
            if (dl) dl.style.display = 'none';
            const items = info.playlist;
            const sel = new Set();
            const wrap = document.createElement('div');
            wrap.id = 'v3-list';
            wrap.className = 'v3-list';
            wrap.innerHTML = `
                <div class="v3-carousel-head"><div><strong>Lista</strong> <span class="v3-hint">· ${items.length} videos</span></div>
                    <button type="button" class="v3-link" data-l="all">Elegir todos</button></div>
                <ul class="v3-list-items">${items.map((it, i) => `
                    <li><label>
                        <input type="checkbox" data-i="${i}">
                        ${it.thumbnail ? `<img src="${esc(it.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<span class="v3-list-noimg material-symbols-outlined">movie</span>'}
                        <span class="v3-list-title">${esc(it.title)}${it.live ? ' <em class="v3-live-tag">EN VIVO</em>' : ''}</span>
                        <span class="v3-list-dur">${it.duration ? fmtTime(it.duration) : ''}</span>
                    </label></li>`).join('')}</ul>
                <div class="v3-list-actions">
                    <select class="field" data-l="lang" title="Idioma"><option value="es">Español</option><option value="en">Inglés</option><option value="original">Original</option></select>
                    <button type="button" class="btn-primary flex-1" data-l="go" disabled><span class="material-symbols-outlined">playlist_add</span> <span>Elegí videos para transcribir</span></button>
                </div>
                <p class="v3-hint">Se transcriben de a uno en segundo plano y quedan en el Historial. Podés seguir usando Clipa mientras tanto.</p>`;
            const first = body.firstElementChild;
            first ? first.insertAdjacentElement('afterend', wrap) : body.prepend(wrap);
            const refresh = () => {
                wrap.querySelectorAll('input[data-i]').forEach(c => { c.checked = sel.has(+c.dataset.i); });
                const go = wrap.querySelector('[data-l="go"]');
                go.disabled = !sel.size;
                go.querySelector('span:last-child').textContent = sel.size ? `Transcribir ${sel.size} ${sel.size === 1 ? 'video' : 'videos'}` : 'Elegí videos para transcribir';
                wrap.querySelector('[data-l="all"]').textContent = sel.size === items.length ? 'Quitar todos' : 'Elegir todos';
            };
            wrap.addEventListener('change', (e) => {
                const i = e.target.dataset?.i;
                if (i == null) return;
                e.target.checked ? sel.add(+i) : sel.delete(+i);
                refresh();
            });
            wrap.addEventListener('click', async (e) => {
                const act = e.target.closest('[data-l]')?.dataset.l;
                if (act === 'all') { if (sel.size === items.length) sel.clear(); else items.forEach((_, i) => sel.add(i)); refresh(); }
                if (act === 'go') {
                    const btn = e.target.closest('button');
                    btn.disabled = true;
                    const lang = wrap.querySelector('[data-l="lang"]').value;
                    let ok = 0;
                    for (const i of [...sel].sort((a, b) => a - b)) {
                        const it = items[i];
                        try { await jobs.create({ url: it.url, lang, title: it.title, uploader: info.uploader, duration: it.duration }); ok++; }
                        catch (err) { toast(`${it.title}: ${err.message}`, 'error'); }
                    }
                    if (ok) {
                        toast(`${ok} ${ok === 1 ? 'video en cola' : 'videos en cola'}. Te aviso cuando terminen.`, 'success');
                        document.getElementById('v3-jobs-btn')?.click();
                    }
                    sel.clear();
                    refresh();
                }
            });
        }

        function mountLive(info, body) {
            const box = document.createElement('div');
            box.id = 'v3-live';
            box.className = 'v3-live';
            const upcoming = info.live_status === 'is_upcoming';
            box.innerHTML = `
                <div class="v3-live-head"><span class="v3-rec-dot"></span><strong>${upcoming ? 'Vivo programado' : 'Está en vivo'}</strong></div>
                ${upcoming ? '<p class="v3-hint">Todavía no empezó. Volvé a analizar el enlace cuando arranque para grabarlo.</p>' : `
                <label class="v3-check"><input type="checkbox" data-r="from_start"> Grabar desde el principio (no solo desde ahora)</label>
                <label class="v3-check"><input type="checkbox" data-r="transcribe" checked> Transcribir al terminar</label>
                <button type="button" class="btn-primary w-full" data-r="go"><span class="material-symbols-outlined">radio_button_checked</span> Grabar el vivo</button>
                <p class="v3-hint">Graba en segundo plano hasta que termine la transmisión o la detengas desde el panel de trabajos. Queda en la carpeta "grabaciones".</p>`}`;
            const first = body.firstElementChild;
            first ? first.insertAdjacentElement('afterend', box) : body.prepend(box);
            box.querySelector('[data-r="go"]')?.addEventListener('click', async (e) => {
                const btn = e.currentTarget;
                btn.disabled = true;
                try {
                    askNotificationPermission();
                    const lang = document.querySelector('.lang-btn.active')?.dataset.lang || 'es';
                    await api('/record', { method: 'POST', body: {
                        url: info.url, from_start: box.querySelector('[data-r="from_start"]').checked,
                        transcribe: box.querySelector('[data-r="transcribe"]').checked, target_lang: lang, groq_api_key: groqKey() } });
                    toast('Grabando. Lo ves y lo detenés desde el panel de trabajos.', 'success', 6000);
                    jobs.poll();
                    document.getElementById('v3-jobs-btn')?.click();
                } catch (err) { toast(err.message, 'error'); }
                btn.disabled = false;
            });
        }

        function mountCommentsButton(info, body) {
            const anchor = document.getElementById('download-thumb-btn')?.closest('.grid');
            if (!anchor) return;
            const btn = document.createElement('button');
            btn.id = 'v3-comments-btn';
            btn.className = 'btn-ghost w-full justify-center';
            btn.innerHTML = `<span class="material-symbols-outlined text-lg">forum</span> Comentarios${info.comment_count ? ` (${Number(info.comment_count).toLocaleString('es-AR')})` : ''}`;
            anchor.insertAdjacentElement('afterend', btn);
            btn.addEventListener('click', () => loadComments(info, btn));
        }

        async function loadComments(info, btn, sort = 'top') {
            document.getElementById('v3-comments')?.remove();
            const box = document.createElement('div');
            box.id = 'v3-comments';
            box.className = 'v3-comments';
            box.innerHTML = '<div class="v3-comments-loading"><span class="v3-spinner v3-spinner-sm"></span> Bajando comentarios (puede tardar un poco)...</div>';
            btn.insertAdjacentElement('afterend', box);
            try {
                const d = await api('/comments', { method: 'POST', body: { url: info.url, limit: 300, sort } });
                const filter = (q) => {
                    const n = normalize(q);
                    return d.comments.filter(c => !n || normalize(c.text + ' ' + c.author).includes(n));
                };
                const render = (list) => list.map(c => `
                    <li class="${c.reply ? 'v3-reply' : ''}">
                        <p class="v3-c-meta"><b>${esc(c.author)}</b>${c.by_uploader ? ' <em>autor</em>' : ''}${c.pinned ? ' <em>fijado</em>' : ''} · ${Number(c.likes).toLocaleString('es-AR')} <span class="material-symbols-outlined">thumb_up</span>${c.when ? ` · ${esc(c.when)}` : ''}</p>
                        <p>${esc(c.text)}</p></li>`).join('') || '<li class="v3-hint">Nada coincide.</li>';
                box.innerHTML = `
                    <div class="v3-comments-bar">
                        <select class="field" data-c="sort"><option value="top" ${sort === 'top' ? 'selected' : ''}>Más votados</option><option value="new" ${sort === 'new' ? 'selected' : ''}>Más nuevos</option></select>
                        <input class="field flex-1" data-c="q" placeholder="Buscar en ${d.comments.length} comentarios...">
                        <button class="icon-btn-sm" data-c="txt" title="Descargar .txt"><span class="material-symbols-outlined">download</span></button>
                        <button class="icon-btn-sm" data-c="close" title="Cerrar"><span class="material-symbols-outlined">close</span></button>
                    </div>
                    <ul class="v3-comments-list">${render(d.comments)}</ul>`;
                box.querySelector('[data-c="q"]').addEventListener('input', (e) => { box.querySelector('ul').innerHTML = render(filter(e.target.value)); });
                box.querySelector('[data-c="sort"]').addEventListener('change', (e) => loadComments(info, btn, e.target.value));
                box.querySelector('[data-c="close"]').addEventListener('click', () => box.remove());
                box.querySelector('[data-c="txt"]').addEventListener('click', () => {
                    downloadBlob(new Blob([d.text], { type: 'text/plain;charset=utf-8' }), `comentarios_${(info.title || 'video').slice(0, 40)}.txt`);
                });
            } catch (err) {
                box.innerHTML = `<p class="v3-err">${esc(err.message)}</p>`;
            }
        }

        function normalize(t) {
            return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
        }

        async function init() {
            await loadSettings();
            mountSettingsCard();
            startEventsPolling();
        }

        return { init, onVideoInfo, settings: () => settings, clear: clearInfoExtras };
    })();

    // ─── Arranque ────────────────────────────────────────────────────────────────
    // ─── Usar desde el celular (3.4) ─────────────────────────────────────────────
    const mobileCard = (() => {
        async function mount() {
            const section = document.getElementById('config-section');
            if (!section || document.getElementById('v3-mobile-card')) return;
            let info;
            try { info = await api('/mobile/info'); } catch { return; }
            if (!info.from_pc) return;           // desde el celular no hace falta explicarlo
            const card = document.createElement('div');
            card.id = 'v3-mobile-card';
            card.className = 'glass card space-y-3';
            const head = `
                <div class="flex items-center gap-3">
                    <span class="quick-icon bg-primary/10 text-primary"><span class="material-symbols-outlined">smartphone</span></span>
                    <h3 class="font-semibold text-white">Usar desde el celular</h3>
                </div>`;
            if (info.enabled) {
                card.innerHTML = head + `
                    <p class="v3-set-help">Activado. Con el celular en el mismo Wi-Fi, escaneá el código con la cámara o abrí la dirección, y escribí el PIN la primera vez. La PC tiene que estar prendida con Clipadsk abierto.</p>
                    <div class="v3-mobile-grid">
                        <div class="v3-qr" id="v3-qr-box" aria-label="Código QR"></div>
                        <div class="v3-mobile-data">
                            ${info.urls.map(u => `<p><b>Dirección</b><br><code>${esc(u)}</code></p>`).join('') || '<p class="v3-err">No se encontró la dirección de la PC en la red.</p>'}
                            <p><b>PIN</b><br><code class="v3-pin">${esc(info.pin || '')}</code></p>
                        </div>
                    </div>
                    <details class="v3-howto">
                        <summary>Cómo dejar un ícono en el celular (Android)</summary>
                        <ol>
                            <li>Abrí la dirección en <b>Chrome</b> del celular (con el QR o escribiéndola) y poné el PIN.</li>
                            <li>Tocá los tres puntos <b>⋮</b>, arriba a la derecha, y elegí <b>Agregar a la pantalla principal</b>.</li>
                            <li>En el cartel "Instalar y crear acceso directo" tocá <b>Crear acceso directo</b>. "Instalar" sale como "No se puede instalar esta app" porque la dirección es http, y es normal.</li>
                            <li>Confirmá el nombre y tocá <b>Agregar</b>. El ícono de Clipadsk queda en la pantalla de inicio y abre la app directo, dentro de Chrome.</li>
                        </ol>
                        <p>Si el ícono sale genérico, borralo y creá el acceso directo de nuevo. Funciona solo con la PC prendida, Clipadsk abierto y el celular en el mismo Wi-Fi.</p>
                    </details>
                    <p class="v3-set-help">Desde el celular se puede transcribir, leer el historial y analizar. Actualizar la app y los ajustes quedan solo en la PC.</p>
                    <button class="btn-ghost" data-m="off"><span class="material-symbols-outlined text-base">phonelink_erase</span> Desactivar acceso desde el celular</button>`;
            } else if (info.exposed) {
                card.innerHTML = head + `<p class="v3-err">Clipadsk está abierto a la red pero sin PIN: cualquiera en tu Wi-Fi podría usarlo. Activalo desde acá para ponerle un PIN.</p>
                    <button class="btn-primary" data-m="on"><span class="material-symbols-outlined text-base">smartphone</span> Activar con PIN</button>`;
            } else {
                card.innerHTML = head + `
                    <p class="v3-set-help">Hoy Clipadsk solo se abre en esta PC. Para usarlo también desde el celular (mismo Wi-Fi, con un PIN), tocá el botón. Windows va a pedir permiso de administrador solo la primera vez (es para abrir el puerto en el firewall) y Clipadsk se reinicia solo, unos 10 segundos. Se apaga cuando quieras desde acá.</p>
                    <button class="btn-primary" data-m="on"><span class="material-symbols-outlined text-base">smartphone</span> Activar acceso desde el celular</button>`;
            }
            const motorCard = document.getElementById('v3-motor-card');
            if (motorCard) motorCard.after(card); else section.appendChild(card);
            drawQr(card.querySelector('#v3-qr-box'), info.urls && info.urls[0]);
            card.addEventListener('click', (e) => {
                const b = e.target.closest('[data-m]');
                if (b) toggle(b.dataset.m === 'on', b);
            });
        }
        /** Activa/desactiva desde la app: el servidor lanza el script, se reinicia, y la página se recarga sola. */
        async function toggle(enable, btn) {
            const msg = enable
                ? 'Clipadsk se va a reiniciar (unos 10 segundos) y, solo la primera vez, Windows va a pedir permiso de administrador para abrir el puerto en el firewall. Aceptalo. Los trabajos en curso se cortan.'
                : 'Clipadsk se va a reiniciar (unos 10 segundos) y va a volver a funcionar solo en esta PC. Los trabajos en curso se cortan.';
            if (!await confirmDialog(msg, { title: enable ? 'Activar acceso desde el celular' : 'Desactivar acceso desde el celular',
                                            okText: enable ? 'Activar' : 'Desactivar' })) return;
            if (btn) btn.disabled = true;
            try {
                await api('/mobile/toggle', { method: 'POST', body: { enable } });
            } catch (err) {
                toast(err.message, 'error');
                if (btn) btn.disabled = false;
                return;
            }
            const card = document.getElementById('v3-mobile-card');
            if (card) card.insertAdjacentHTML('beforeend', '<p class="v3-set-help v3-restarting">Reiniciando Clipadsk... aceptá el permiso de Windows si aparece. Esta página se recarga sola.</p>');
            // Esperar a que el servidor se apague y vuelva a responder
            await new Promise(r => setTimeout(r, 5000));
            for (let i = 0; i < 40; i++) {
                try {
                    const r = await fetch(`${API}/health`, { cache: 'no-store' });
                    if (r.ok) { location.reload(); return; }
                } catch { /* todavía reiniciando */ }
                await new Promise(r => setTimeout(r, 2000));
            }
            toast('Clipadsk tarda en volver. Recargá la página en unos segundos.', 'info', 8000);
        }

        /** QR dibujado en el navegador (librería incluida en vendor/): no depende de nada instalado en Python. */
        function drawQr(box, url) {
            if (!box) return;
            if (!url || typeof window.qrcode !== 'function') { box.remove(); return; }
            try {
                const qr = window.qrcode(0, 'M');
                qr.addData(url);
                qr.make();
                box.innerHTML = qr.createSvgTag({ cellSize: 5, margin: 2, scalable: true });
                const svg = box.querySelector('svg');
                if (svg) { svg.setAttribute('width', '160'); svg.setAttribute('height', '160'); }
            } catch { box.remove(); }
        }
        return { mount };
    })();

    // En http (no https) los navegadores del celular no tienen el portapapeles moderno: se usa el método viejo.
    if (!navigator.clipboard) {
        const legacyCopy = (text) => new Promise((resolve, reject) => {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            let ok = false;
            try { ok = document.execCommand('copy'); } catch { ok = false; }
            ta.remove();
            ok ? resolve() : reject(new Error('No se pudo copiar'));
        });
        try { Object.defineProperty(navigator, 'clipboard', { value: { writeText: legacyCopy }, configurable: true }); } catch { /* sin portapapeles */ }
    }

    // ─── Aviso de versión nueva (consulta a GitHub como mucho cada 12 horas) ─────
    async function checkNewVersion() {
        try {
            const last = Number(store.get('clipadsk_version_check') || 0);
            if (Date.now() - last < 12 * 3600 * 1000) return;
            const v = await api('/version/latest');
            store.set('clipadsk_version_check', String(Date.now()));
            if (!v.newer) return;
            toast(`Hay una versión nueva de Clipadsk (${v.latest}; tenés la ${v.current}). Actualizá desde Configuración → Actualizar aplicación.`, 'info', 12000);
            const btn = document.getElementById('system-update-app-btn');
            if (btn && !btn.querySelector('.v3-new-badge')) btn.insertAdjacentHTML('beforeend', `<span class="v3-new-badge">Nueva ${esc(v.latest)}</span>`);
        } catch { /* sin internet o GitHub no responde: no molesta */ }
    }

    document.addEventListener('clipa:ready', () => {
        setTimeout(checkNewVersion, 4000);
        setTimeout(() => mobileCard.mount(), 800);
        mountJobsPanel();
        mountGlobalDrop();
        mountPasteToAnalyze();
        mountShortcuts();
        checkCookiesBanner();
        history.migrateFromBrowser().then(() => history.load());
        motor.init();
    });

    document.addEventListener('clipa:transcript', (e) => {
        const d = e.detail || {};
        viewer.mount({ segments: d.segments, source: d.source });
        mountRawToggle({ text: d.text, raw: d.raw, segments: d.segments });
    });

    // ─── COPY DE LA PUBLICACIÓN ──────────────────────────────────────────────
    // Muestra el texto que acompaña el post (Instagram, TikTok, YouTube…) y lo analiza con IA sin transcribir.
    const copyBox = (() => {
        function unmount() { document.getElementById('v3-copy')?.remove(); }

        function mount(info) {
            unmount();
            const text = (info?.copy || (info?.carousel ? info.description : '') || '').trim();
            if (text.length < 10 || info.playlist) return;
            const body = document.querySelector('#video-info-card .p-6');
            if (!body) return;
            const box = document.createElement('div');
            box.id = 'v3-copy';
            box.className = 'v3-copy';
            box.innerHTML = `
                <div class="v3-carousel-head">
                    <div><strong>Copy de la publicación</strong> <span class="v3-hint">· ${text.length} caracteres</span></div>
                    <button type="button" class="v3-link" data-act="copy-text">Copiar</button>
                </div>
                <div class="v3-copy-text">${esc(text)}</div>
                <button type="button" class="v3-link v3-copy-more hidden" data-act="more">Ver todo</button>
                <button type="button" class="btn-soft w-full" data-act="analyze">
                    <span class="material-symbols-outlined">edit_note</span> Analizar el copy
                </button>
                <div class="v3-copy-out hidden"></div>`;
            const anchor = document.getElementById('v3-carousel') || body.firstElementChild;
            anchor ? anchor.insertAdjacentElement('afterend', box) : body.prepend(box);
            const txt = box.querySelector('.v3-copy-text');
            requestAnimationFrame(() => { if (txt.scrollHeight > txt.clientHeight + 4) box.querySelector('.v3-copy-more').classList.remove('hidden'); });
            box.addEventListener('click', async (e) => {
                const btn = e.target.closest('button[data-act]');
                if (!btn) return;
                if (btn.dataset.act === 'more') { txt.classList.toggle('open'); btn.textContent = txt.classList.contains('open') ? 'Ver menos' : 'Ver todo'; }
                else if (btn.dataset.act === 'copy-text') { navigator.clipboard?.writeText(text); toast('Copy copiado', 'success'); }
                else if (btn.dataset.act === 'analyze') analyze(text, btn, box.querySelector('.v3-copy-out'));
            });
        }

        async function analyze(text, btn, out) {
            btn.disabled = true;
            out.classList.remove('hidden');
            out.innerHTML = '<p class="v3-hint">Analizando el copy con IA…</p>';
            try {
                const data = await api('/analyze', { method: 'POST', body: {
                    mode: 'copy', copy: text, transcript: window.Clipa?.getTranscript?.() || '',
                    groq_api_key: localStorage.getItem('clipadsk_groq_api_key') || undefined } });
                const html = window.Clipa?.formatAI ? window.Clipa.formatAI(data.result) : esc(data.result).replace(/\n/g, '<br>');
                out.innerHTML = `<div class="v3-carousel-head"><strong>Análisis del copy</strong>
                    <button type="button" class="v3-link" data-act="copy-result">Copiar</button></div>
                    <div class="v3-copy-result">${html}</div>`;
                out.querySelector('[data-act="copy-result"]').onclick = (ev) => {
                    ev.stopPropagation();
                    navigator.clipboard?.writeText(out.querySelector('.v3-copy-result').innerText);
                    toast('Análisis copiado', 'success');
                };
            } catch (err) {
                out.innerHTML = `<p class="v3-copy-err">${esc(err.message || 'No se pudo analizar el copy')}</p>`;
            } finally {
                btn.disabled = false;
            }
        }

        return { mount, unmount };
    })();

    document.addEventListener('clipa:tab', () => { viewer.unmount(); gallery.unmount(); motor.clear(); copyBox.unmount(); });
    document.addEventListener('clipa:videoinfo', (e) => { showEstimate(e.detail || {}); gallery.mount(e.detail || {}); motor.onVideoInfo(e.detail || {}); copyBox.mount(e.detail || {}); });

    window.ClipaV3 = {
        gallery,
        motor,
        copyBox,
        version: '3.0.0', api, history, jobs, viewer, confirm: confirmDialog, prompt: promptDialog, dialog,
        formatQuote, linkAt, fmtTime, parseTime, youtubeId, estimateTranscription,
    };
})();
