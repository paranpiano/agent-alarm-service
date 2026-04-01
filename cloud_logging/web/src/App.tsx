import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import LogViewer from './pages/LogViewer';

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-white">
        <nav className="bg-gray-800 border-b border-gray-700 px-6 py-3 flex items-center gap-6">
          <span className="text-blue-400 font-bold text-sm">AI Alarm Monitor</span>
          <NavLink to="/" end className={({ isActive }) =>
            `text-sm transition-colors ${isActive ? 'text-white font-semibold' : 'text-gray-400 hover:text-white'}`}>
            Dashboard
          </NavLink>
          <NavLink to="/logs" className={({ isActive }) =>
            `text-sm transition-colors ${isActive ? 'text-white font-semibold' : 'text-gray-400 hover:text-white'}`}>
            Log Viewer
          </NavLink>
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/logs" element={<LogViewer />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
