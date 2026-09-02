/**
 * 应用根组件：#/ → 书架入口；#/read/<bookId> → 阅读页。
 */
import BookShelf from "./BookShelf";
import ReaderPage from "./reader/ReaderPage";
import { useHashRoute } from "./reader/useHashRoute";

export default function App() {
  const path = useHashRoute();
  const readMatch = path.match(/^\/read\/([0-9a-f]{16})$/);
  if (readMatch) return <ReaderPage bookId={readMatch[1]} />;
  return <BookShelf />;
}
