import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import ClassifyPage from './pages/ClassifyPage';
import BrowsePage from './pages/BrowsePage';

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: '8px 24px', borderBottom: '1px solid #eee' }}>
        <Link to="/" style={{ marginRight: 16 }}>분류</Link>
        <Link to="/browse">HSK 탐색</Link>
      </nav>
      <Routes>
        <Route path="/" element={<ClassifyPage />} />
        <Route path="/browse" element={<BrowsePage />} />
      </Routes>
    </BrowserRouter>
  );
}
