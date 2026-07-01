/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class", // Activa el modo oscuro nativo que tienen tus HTML
  content: [
    "./src/**/*.{html,ts}",
  ],
  theme: {
    extend: {
      colors: {
        // ==========================================
        // PALETA UNIFICADA BLACK PENGUIN (ÁMBAR/DARK)
        // ==========================================
        
        // Fondos y Superficies
        "background": "#0A0A0A",
        "primary-container": "#0a0a0a",
        "surface-dim": "#131313",
        "surface-level-1": "#161616",
        "surface-variant": "#353535",
        
        // Textos y Grises (Tipografía)
        "primary": "#c9c6c5",
        "on-surface": "#e4e2e1",
        "inverse-surface": "#e4e2e1",
        "surface-tint": "#c9c6c5",
        "on-surface-variant": "#c4c7c7",
        "gray-custom": "#999999",
        "on-primary-container": "#7b7979",
        "on-tertiary-container": "#7a7979",
        
        // Acentos (Ámbar / Oro)
        "secondary": "#E99E10",
        "on-secondary": "#452b00",
        "secondary-fixed-dim": "#ffb94e",
        
        // Terciarios y Variantes
        "tertiary": "#c8c6c5",
        "tertiary-fixed": "#e5e2e1",
        "tertiary-fixed-dim": "#c8c6c5",
        "on-tertiary-fixed-variant": "#474746",
        "on-primary-fixed-variant": "#474646",
        
        // Bordes y Líneas
        "border-level-2": "#2E2E2E",
        "outline-variant": "#474746"
      },
      fontFamily: {
        // Unificamos la fuente a Space Grotesk para todo el proyecto
        "sans": ["Space Grotesk", "sans-serif"],
        "caption": ["Space Grotesk", "sans-serif"],
        "label-ui": ["Space Grotesk", "sans-serif"]
      }
    }
  },
  plugins: [
    // El diseño usó plugins nativos de tailwind, si te da error en consola más adelante los instalamos
    // require('@tailwindcss/forms'),
    // require('@tailwindcss/container-queries')
  ],
}