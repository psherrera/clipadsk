const CACHE_NAME = 'clipadsk-v3.2';
const ASSETS = [
    './',
    './index.html',
    './style.css?v=3.2',
    './main.js?v=3.2',
    './v3.js?v=3.2',
    './v3.css?v=3.2',
    './vendor/tailwind.css?v=3.2',
    './vendor/fonts.css',
    './vendor/jszip.min.js',
    './vendor/fonts/outfit-latin-wght-normal.woff2',
    './vendor/fonts/outfit-latin-ext-wght-normal.woff2',
    './vendor/fonts/material-symbols-outlined.woff2',
    './icon.svg',
    './manifest.json'
];

// Instalar y Cachear recursos críticos
self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

// Activar y limpiar cachés antiguos
self.addEventListener('activate', (event) => {
    event.waitUntil(
        Promise.all([
            self.clients.claim(),
            caches.keys().then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cache) => {
                        if (cache !== CACHE_NAME) {
                            console.log('SW: Borrando caché antiguo:', cache);
                            return caches.delete(cache);
                        }
                    })
                );
            })
        ])
    );
});

// Estrategia Network-First con Fallback a Caché
self.addEventListener('fetch', (event) => {
    // No interceptamos peticiones a la API
    if (event.request.url.includes('/api/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Si la red responde, clonamos y guardamos en caché
                if (response && response.status === 200 && response.type === 'basic') {
                    const responseToCache = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseToCache);
                    });
                }
                return response;
            })
            .catch(() => {
                // Si la red falla (offline), devolvemos del caché
                return caches.match(event.request);
            })
    );
});
