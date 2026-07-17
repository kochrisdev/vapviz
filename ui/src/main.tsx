import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ThemeProvider } from "./lib/theme";
import "@fontsource/silkscreen/400.css"; // pixel display face — self-hosted, OFL
import "@fontsource/silkscreen/700.css";
import "@fontsource/pixelify-sans/400.css"; // pixel body face — all reading text
import "@fontsource/pixelify-sans/500.css";
import "@fontsource/pixelify-sans/600.css";
import "@fontsource/vt323/400.css"; // pixel terminal face — JSON, logs, durations
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ErrorBoundary label="the app">
        <App />
      </ErrorBoundary>
    </ThemeProvider>
  </React.StrictMode>
);
