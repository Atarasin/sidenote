import { useEffect, useState } from "react";

/** 极简 hash 路由：#/read/<bookId> → "/read/<bookId>"。 */

function readHash(): string {
  const h = window.location.hash;
  return h.startsWith("#") ? h.slice(1) : "/";
}

export function useHashRoute(): string {
  const [path, setPath] = useState(readHash);
  useEffect(() => {
    const onChange = () => setPath(readHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path;
}

export function navigate(path: string): void {
  window.location.hash = path;
}
