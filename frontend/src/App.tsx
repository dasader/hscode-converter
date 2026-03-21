import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import ClassifyPage from './pages/ClassifyPage';
import BrowsePage from './pages/BrowsePage';
import { version } from '../package.json';
import './App.css';

export default function App() {
  return (
    <BrowserRouter>
      <div className="accent-stripe" />
      <nav className="nav">
        <div className="nav-inner">
          <NavLink to="/" className="nav-brand">
            <span className="nav-brand-icon">HS</span>
            HSCode Connector
          </NavLink>
          <div className="nav-links">
            <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              기술 분류
            </NavLink>
            <NavLink to="/browse" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              코드 탐색
            </NavLink>
          </div>
        </div>
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<ClassifyPage />} />
          <Route path="/browse" element={<BrowsePage />} />
        </Routes>
      </main>
      <footer className="app-footer">
        <span className="footer-brand">blinktask.work</span>
        <span className="footer-version">v{version}</span>
      </footer>
    </BrowserRouter>
  );
}
