import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        coal: '#141614',
        chalk: '#e8e0cf',
        moss: '#7eb88d',
        ember: '#dc7d4e',
        brass: '#a79252',
        ink: '#1f241f'
      },
      boxShadow: {
        ledger: '0 24px 80px rgba(0, 0, 0, 0.24)'
      },
      fontFamily: {
        display: ['Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', 'serif'],
        body: ['Avenir Next', 'Segoe UI', 'sans-serif'],
        mono: ['SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace']
      }
    }
  },
  plugins: []
};

export default config;
