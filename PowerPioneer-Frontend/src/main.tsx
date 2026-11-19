import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./integration.css";
import "./timeline.css";
import "./theme-evening.generated.css";
import "./daypart.css";
import "./copilot.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
