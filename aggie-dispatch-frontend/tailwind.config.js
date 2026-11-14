/* Same theme as the inline `tailwind.config` in index.html (Tailwind Play CDN, v3).
   Build a local stylesheet so the page renders without internet:
   npx tailwindcss@3.4.17 -c tailwind.config.js -i tailwind.input.css -o tailwind.css --minify */
module.exports = {
  content: ['./index.html', './api-bridge.js'],
  theme: {
    extend: {
      colors: {
        aggie: {
          blue: '#004684',
          navy: '#002D56',
          gold: '#FDB927',
          goldSoft: '#FEF7E6',
          paper: '#FAF9F5',
          ink: '#111827',
        },
      },
      fontFamily: {
        serif: ['Newsreader', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
};
