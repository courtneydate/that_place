/**
 * Root application component.
 * Routes are split by user type: Fieldmouse Admin vs tenant user.
 */
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import FieldmouseAdminLayout from './layouts/FieldmouseAdminLayout';
import TenantLayout from './layouts/TenantLayout';
import Login from './pages/Login';
import AcceptInvite from './pages/AcceptInvite';
import TenantList from './pages/admin/TenantList';
import TenantCreate from './pages/admin/TenantCreate';
import TenantDetail from './pages/admin/TenantDetail';
import DeviceTypeLibrary from './pages/admin/DeviceTypeLibrary';
import PendingDevices from './pages/admin/PendingDevices';
import UserManagement from './pages/tenant/UserManagement';
import Sites from './pages/tenant/Sites';
import Groups from './pages/tenant/Groups';
import Settings from './pages/tenant/Settings';
import Devices from './pages/tenant/Devices';

function App() {
  const { user } = useAuth();

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<Login />} />
      <Route path="/accept-invite/:token" element={<AcceptInvite />} />

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
        <Route path="device-types" element={<DeviceTypeLibrary />} />
        <Route path="pending-devices" element={<PendingDevices />} />
      </Route>

      {/* Tenant user routes */}
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <TenantLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/app/users" replace />} />
        <Route path="users" element={<UserManagement />} />
        <Route path="sites" element={<Sites />} />
        <Route path="devices" element={<Devices />} />
        <Route path="groups" element={<Groups />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      {/* Root redirect — FM Admins → /admin, tenant users → /app */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            {user === null
              ? null /* wait for user profile to load */
              : user.is_fieldmouse_admin
                ? <Navigate to="/admin/tenants" replace />
                : <Navigate to="/app/users" replace />
            }
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
