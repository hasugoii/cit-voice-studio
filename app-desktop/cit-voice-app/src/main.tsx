import React from "react";
import ReactDOM from "react-dom/client";
import App from "@/app";
import { AdminSessionGuard } from "@/components/admin-session-guard";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AdminSessionGuard />
    <App />
  </React.StrictMode>
);
