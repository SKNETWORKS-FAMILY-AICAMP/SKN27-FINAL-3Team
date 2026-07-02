import React from "react";
import { createRoot } from "react-dom/client";

import FrontendAppShell from "./FrontendAppShell.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <FrontendAppShell
      apiBase="/api"
      authToken="dev-mock-token"
      googleClientId={import.meta.env.VITE_GOOGLE_CLIENT_ID || ""}
    />
  </React.StrictMode>
);
