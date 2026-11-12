/* Configuración de Tailwind (antes estaba inline en index.html). Se compila con scripts/build_css.ps1 */
// Los grises (slate), "white" y "black" usan variables CSS: en modo claro se invierten,
        // así las clases que genera main.js (text-white, bg-white/5, text-slate-400...) se ven
        // bien en los dos temas sin reescribir cada plantilla.
        const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
        module.exports = {
            content: ['./frontend/index.html', './frontend/setup.html', './frontend/main.js'],
            plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')],
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        primary: v('c-primary'),
                        accent: v('c-accent'),
                        "background-dark": v('c-bg'),
                        onaccent: "#ffffff",
                        white: v('c-white'),
                        black: v('c-black'),
                        slate: {
                            50: v('s50'), 100: v('s100'), 200: v('s200'), 300: v('s300'), 400: v('s400'),
                            500: v('s500'), 600: v('s600'), 700: v('s700'), 800: v('s800'), 900: v('s900'), 950: v('s950'),
                        },
                    },
                    fontFamily: { display: ["Outfit", "Inter", "sans-serif"] },
                },
            },
        };
