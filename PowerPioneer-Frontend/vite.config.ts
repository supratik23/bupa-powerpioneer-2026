import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // The repo lives in a OneDrive-synced folder, where native file-change events
    // are sometimes missed and the dev server keeps serving stale modules.
    watch: { usePolling: true, interval: 300 },
  },
});
