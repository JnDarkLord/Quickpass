/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#0066FF',
          700: '#0052CC',
          800: '#1e40af',
          900: '#122A42',
          navy: '#122A42',
          slate: '#4A607A',
          blue: '#0066FF',
          'blue-hover': '#0052CC',
          sky: '#A4D0E9',
          'sky-border': '#8CB8D4',
          canvas: '#F4F8FB',
          surface: '#FFFFFF',
          'surface-alt': '#EDF4FA',
          border: '#D1DCE5',
          'input-border': '#B8C8D6',
        }
      }
    },
  },
  plugins: [],
}
