import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "orchestrator-theme";

function stored(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** Dark is the default. The choice is kept in localStorage and written to <html data-theme> (see styles.css). */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* private mode: the choice just is not remembered */
    }
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return [theme, toggle];
}
