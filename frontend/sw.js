const CACHE_NAME = 'streamvault-v2.0';
const ASSETS = [
    './',
    './index.html',
    './style.css?v=2.0',
    './main.js?v=2.0',
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
