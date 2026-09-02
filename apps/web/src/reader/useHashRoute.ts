import { useEffect, useState } from "react";

/** 极简 hash 路由：#/read/<bookId> → "/read/<bookId>"。 */

export function useHashRoute(): string {
  const read = () => {
    const h = window.location.hash;
    return h.startsWith("#") ? h.slice(1) : "/";
  };
  const [path, setPath] = useState(read);
  useEffect(() => {
    const onChange = () => setPath(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path;
}

export function navigate(path: string): void {
  window.location.hash = path;
}
