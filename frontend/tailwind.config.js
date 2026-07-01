/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,ts}", // Angular detectará las clases en templates HTML y componentes TS
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Poppins', 'sans-serif'], // Establecemos Poppins como la tipografía base predeterminada
      },
      colors: {
        // Paleta Dark Luxury extraída de los diseños de Black Penguin
        brand: {
          bg: '#050506',       // Fondo maestro ultra oscuro de la interfaz (casi negro terminal)
          surface: '#111113',  // Superficie de tarjetas, cajas de texto y paneles internos
          border: '#222226',   // Gris metálico sutil para divisores, grillas Bloomberg y bordes
          muted: '#8A8A93',    // Gris atenuado ideal para subtextos o placeholders
          white: '#F5F5F7',    // Blanco premium de alto contraste para textos y lectura descansada
          
          // Acentos y estados dinámicos del "Ice Blue"
          accent: '#00D2FF',   // Azul Hielo / Cyan brillante para botones CTA ("Request Access Key", etc.)
          'accent-hover': '#00B4DC',
          glow: 'rgba(0, 210, 255, 0.15)', // Sombra con brillo para efectos de enfoque (foco de inputs)
        }
      },
      boxShadow: {
        // Efecto Bloomberg Terminal / Premium Glow
        'brand-glow': '0 0 20px rgba(0, 210, 255, 0.15)',
      }
    },
  },
  plugins: [],
}