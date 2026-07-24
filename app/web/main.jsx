import React from "react";
import { createRoot } from "react-dom/client";

import FrontendAppShell from "./FrontendAppShell.jsx?mockup-v16";
import "./styles.css?mockup-v16";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <FrontendAppShell
      apiBase="/api"
      googleClientId={import.meta.env.VITE_GOOGLE_CLIENT_ID || ""}
    />
  </React.StrictMode>
);
