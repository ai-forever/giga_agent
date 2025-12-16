import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { GlobalStyle } from "./styles/GlobalStyle";
import "./style.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);

root.render(
  <>
    <GlobalStyle />
    <App />
  </>,
);

if (typeof window !== "undefined") {
  const root = document.getElementById("root");
  if (root) root.style.opacity = "1";
}
