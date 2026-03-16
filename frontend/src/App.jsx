/**
 * Root application component.
 * Routes added sprint by sprint — see ROADMAP.md.
 */
import { Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import ProtectedRoute from './components/ProtectedRoute';

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Protected routes added from Sprint 2 onwards */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <div>Fieldmouse — authenticated placeholder</div>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
