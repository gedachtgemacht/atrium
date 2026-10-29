import { defineConfig, type Plugin } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { resolve } from 'node:path'

// In dev, /g/<token> is the guest app, like in production.
const guestPages: Plugin = {
  name: 'atrium-guest-pages',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url && /^\/g\/(?!api\/|ws)/.test(req.url)) req.url = '/guest.html'
      next()
    })
  },
}

const backend = process.env.ATRIUM_BACKEND ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [svelte(), guestPages],
  build: {
    rollupOptions: {
      input: { index: resolve(__dirname, 'index.html'), guest: resolve(__dirname, 'guest.html') },
    },
  },
  server: {
    proxy: {
      '/api': backend,
      '/g/api': backend,
      '/ws': { target: backend, ws: true },
      '/g/ws': { target: backend, ws: true },
    },
  },
})
