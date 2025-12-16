import { useEffect, useState } from "react";

export const useDarkMode = () => {
  const [isDarkMode, setIsDarkMode] = useState(checkDarkMode());

  function checkDarkMode() {
    return document.documentElement.classList.contains("dark");
  }

  useEffect(() => {
    setIsDarkMode(checkDarkMode);

    const mutationObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "class") {
          setIsDarkMode(checkDarkMode());
        }
      });
    });

    mutationObserver.observe(document.documentElement, { attributes: true });

    return () => {
      mutationObserver.disconnect();
    };
  }, []);

  return isDarkMode;
};
