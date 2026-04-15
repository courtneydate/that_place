/**
 * Root application component.
 * Routes are split by user type: That Place Admin vs tenant user.
 */
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import ThatPlaceAdminLayout from './layouts/ThatPlaceAdminLayout';
import TenantLayout from './layouts/TenantLayout';
import Login from './pages/Login';
import AcceptInvite from './pages/AcceptInvite';
import TenantList from './pages/admin/TenantList';
import TenantCreate from './pages/admin/TenantCreate';
import TenantDetail from './pages/admin/TenantDetail';
import DeviceTypeLibrary from './pages/admin/DeviceTypeLibrary';
import PendingDevices from './pages/admin/PendingDevices';
import ProviderLibrary from './pages/admin/ProviderLibrary';
import FeedProviders from './pages/admin/FeedProviders';
import ReferenceDatasets from './pages/admin/ReferenceDatasets';
import FeedSubscriptions from './pages/tenant/FeedSubscriptions';
import DatasetAssignments from './pages/tenant/DatasetAssignments';
import UserManagement from './pages/tenant/UserManagement';
import Sites from './pages/tenant/Sites';
import Groups from './pages/tenant/Groups';
import Settings from './pages/tenant/Settings';
import Devices from './pages/tenant/Devices';
import DeviceDetail from './pages/tenant/DeviceDetail';
import DataSources from './pages/tenant/DataSources';
import Dashboards from './pages/tenant/Dashboards';
import DashboardDetail from './pages/tenant/DashboardDetail';
import Rules from './pages/tenant/Rules';
import RuleBuilder from './pages/tenant/RuleBuilder';
import RuleDetail from './pages/tenant/RuleDetail';

function App() {
  const { user } = useAuth();

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<Login />} />
      <Route path="/accept-invite/:token" element={<AcceptInvite />} />

      {/* That Place Admin routes */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <ThatPlaceAdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/admin/tenants" replace />} />
        <Route path="tenants" element={<TenantList />} />
        <Route path="tenants/new" element={<TenantCreate />} />
        <Route path="tenants/:id" element={<TenantDetail />} />
        <Route path="device-types" element={<DeviceTypeLibrary />} />
        <Route path="pending-devices" element={<PendingDevices />} />
        <Route path="api-providers" element={<ProviderLibrary />} />
        <Route path="feed-providers" element={<FeedProviders />} />
        <Route path="reference-datasets" element={<ReferenceDatasets />} />
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
        <Route path="dashboards" element={<Dashboards />} />
        <Route path="dashboards/:id" element={<DashboardDetail />} />
        <Route path="users" element={<UserManagement />} />
        <Route path="sites" element={<Sites />} />
        <Route path="devices" element={<Devices />} />
        <Route path="devices/:id" element={<DeviceDetail />} />
        <Route path="data-sources" element={<DataSources />} />
        <Route path="groups" element={<Groups />} />
        <Route path="rules" element={<Rules />} />
        <Route path="rules/new" element={<RuleBuilder />} />
        <Route path="rules/:id" element={<RuleDetail />} />
        <Route path="rules/:id/edit" element={<RuleBuilder />} />
        <Route path="feed-subscriptions" element={<FeedSubscriptions />} />
        <Route path="dataset-assignments" element={<DatasetAssignments />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      {/* Root redirect — FM Admins → /admin, tenant users → /app */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            {user === null
              ? null /* wait for user profile to load */
              : user.is_that_place_admin
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
