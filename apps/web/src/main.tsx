import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installRafShim } from "./reader/epubCompat";

installRafShim();
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
