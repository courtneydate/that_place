/**
 * Root application component.
 * Routes are split by user type: Fieldmouse Admin vs tenant user.
 */
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import FieldmouseAdminLayout from './layouts/FieldmouseAdminLayout';
import Login from './pages/Login';
import TenantList from './pages/admin/TenantList';
import TenantCreate from './pages/admin/TenantCreate';
import TenantDetail from './pages/admin/TenantDetail';

function App() {
  const { user } = useAuth();

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<Login />} />

      {/* Fieldmouse Admin routes */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <FieldmouseAdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/admin/tenants" replace />} />
        <Route path="tenants" element={<TenantList />} />
        <Route path="tenants/new" element={<TenantCreate />} />
        <Route path="tenants/:id" element={<TenantDetail />} />
      </Route>

      {/* Root redirect — FM Admins go to /admin, tenant users go to /dashboard (Sprint 3+) */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            {user?.is_fieldmouse_admin
              ? <Navigate to="/admin/tenants" replace />
              : <div>Tenant dashboard — coming in Sprint 3</div>
            }
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
