import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Register the service worker in production builds only, so the dev server
// is never shadowed by a stale cache. It caches the app shell so the field
// app opens with no signal; it deliberately never caches /api responses.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // A failed registration is not fatal: everything works online, and the
      // field view still keeps its own visible local snapshot.
    });
  });
}
