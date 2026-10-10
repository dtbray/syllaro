import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({
    resolve: {
        alias: { $lib: fileURLToPath(new URL('./src/lib', import.meta.url)) },
    },
    plugins: [svelte(), tailwindcss()],
    server: {
        proxy: {
            '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
        },
    },
});
