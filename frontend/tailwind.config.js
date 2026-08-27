/** @type {import('tailwindcss').Config} */
// ─────────────────────────────────────────────────────────────
// Kora — Plataforma de Auditoria Contábil Municipal
// Design system: "Soft Structuralism" — warm bone canvas, cool
// near-black ink, a single deep gold accent, soft diffused ambient
// shadows, exaggerated squircle radii and machined double-bezel cards.
// Type: Space Grotesk (display) · Plus Jakarta Sans (UI) · JetBrains Mono.
// ─────────────────────────────────────────────────────────────
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F4F2EE',        // warm bone page background
        surface: '#FFFFFF',       // card / panel core
        ink: '#191A1F',           // primary text (cool near-black, never #000)

        // Warm-neutral stone ramp
        stone: {
          50:  '#FAF9F7',
          100: '#F3F1EC',
          150: '#ECE9E3',
          200: '#E4E0D8',
          300: '#D2CDC2',
          400: '#A8A296',
          500: '#7C766B',
          600: '#575249',
          700: '#3C3830',
          800: '#272420',
          900: '#191A1F',
        },

        // Deep gold — the one accent that carries every primary action
        gold: {
          DEFAULT: '#9C7A16',
          hover:   '#846513',
          deep:    '#5A470E',
          wash:    '#F7EFD6',
          soft:    '#FBF7E8',
          ring:    '#E2CC85',
        },

        // Functional status — saturated ink over a pale wash
        success: { DEFAULT: '#127A54', bg: '#E5F3EC', ring: '#BFE3D1' },
        warning: { DEFAULT: '#B26A00', bg: '#FBF0DB', ring: '#F0D8A6' },
        danger:  { DEFAULT: '#C33421', bg: '#FBE8E4', ring: '#F1C7BE' },
        info:    { DEFAULT: '#2E5BD8', bg: '#E8EDFC', ring: '#C3D2F5' },
      },

      fontFamily: {
        sans:    ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', '"Plus Jakarta Sans"', 'ui-sans-serif', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },

      letterSpacing: {
        tightest: '-0.045em',
        tighter:  '-0.03em',
        tight:    '-0.02em',
        snug:     '-0.011em',
        eyebrow:  '0.22em',
      },

      borderRadius: {
        md: '10px', lg: '14px', xl: '18px', '2xl': '22px', '3xl': '28px', '4xl': '34px', pill: '9999px',
      },

      boxShadow: {
        soft:   '0 1px 2px rgba(25,26,31,0.04), 0 2px 8px rgba(25,26,31,0.045)',
        card:   '0 1px 3px rgba(25,26,31,0.04), 0 10px 26px -8px rgba(25,26,31,0.09)',
        lift:   '0 2px 6px rgba(25,26,31,0.05), 0 24px 52px -14px rgba(25,26,31,0.16)',
        float:  '0 4px 12px rgba(25,26,31,0.06), 0 36px 70px -18px rgba(25,26,31,0.22)',
        insetHi:'inset 0 1px 0 rgba(255,255,255,0.7)',
        ringHair:'0 0 0 1px rgba(25,26,31,0.06)',
        focus:  '0 0 0 4px rgba(156,122,22,0.16)',
      },

      transitionTimingFunction: {
        // spring-ish expo-out and a smooth glide
        expo:  'cubic-bezier(0.22, 1, 0.36, 1)',
        glide: 'cubic-bezier(0.32, 0.72, 0, 1)',
        back:  'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },

      transitionDuration: {
        250: '250ms', 400: '400ms', 600: '600ms', 800: '800ms',
      },

      keyframes: {
        'reveal-up': {
          '0%':   { opacity: '0', transform: 'translateY(18px)', filter: 'blur(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)', filter: 'blur(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' }, '100%': { opacity: '1' },
        },
        'scale-in': {
          '0%':   { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' },
        },
        'spin-slow': { to: { transform: 'rotate(360deg)' } },
        'pulse-ring': {
          '0%':   { boxShadow: '0 0 0 0 rgba(156,122,22,0.30)' },
          '70%':  { boxShadow: '0 0 0 10px rgba(156,122,22,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(156,122,22,0)' },
        },
        'bar-grow': {
          '0%': { transform: 'scaleX(0)' }, '100%': { transform: 'scaleX(1)' },
        },
      },

      animation: {
        'reveal-up': 'reveal-up 0.8s cubic-bezier(0.22,1,0.36,1) both',
        'fade-in':   'fade-in 0.5s ease both',
        'scale-in':  'scale-in 0.4s cubic-bezier(0.22,1,0.36,1) both',
        shimmer:     'shimmer 1.8s linear infinite',
        'spin-slow': 'spin-slow 0.9s linear infinite',
        'pulse-ring':'pulse-ring 1.8s cubic-bezier(0.22,1,0.36,1) infinite',
      },

      maxWidth: {
        content: '1180px',
      },
    },
  },
  plugins: [],
}
