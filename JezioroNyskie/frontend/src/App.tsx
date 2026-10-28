import { Route, Routes } from 'react-router-dom';
import { HistoryPage } from './pages/HistoryPage';
import { MapPage } from './pages/MapPage';
import { MethodPage } from './pages/MethodPage';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<MapPage />} />
      <Route path="/historia" element={<HistoryPage />} />
      <Route path="/metoda" element={<MethodPage />} />
    </Routes>
  );
}
