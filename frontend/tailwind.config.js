/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#0a0a0a',
        foreground: '#ededed',
        primary: '#ff4444',
        'primary-dark': '#cc3333',
        secondary: '#ff8c42',
        'secondary-dark': '#ff6b33',
        surface: '#1a1a1a',
        'surface-light': '#252525',
        border: '#333333',
        muted: '#666666',
      },
      fontFamily: {
        mono: ['var(--font-geist-mono)'],
        sans: ['var(--font-geist-sans)'],
      },
    },
  },
  plugins: [],
}
