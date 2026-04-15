/**
 * Layout wrapper for That Place Admin pages.
 *
 * Separate from the tenant user layout — That Place Admins manage the platform,
 * not individual tenant data. Renders a top navigation bar and a main
 * content area.
 */
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import styles from './ThatPlaceAdminLayout.module.css';

function ThatPlaceAdminLayout() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <span className={styles.brand}>That Place Admin</span>
        <nav className={styles.nav}>
          <NavLink
            to="/admin/tenants"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Tenants
          </NavLink>
          <NavLink
            to="/admin/device-types"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Device Types
          </NavLink>
          <NavLink
            to="/admin/pending-devices"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Pending Devices
          </NavLink>
          <NavLink
            to="/admin/api-providers"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            API Providers
          </NavLink>
          <NavLink
            to="/admin/feed-providers"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Feed Providers
          </NavLink>
          <NavLink
            to="/admin/reference-datasets"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Reference Datasets
          </NavLink>
        </nav>
        <button onClick={handleLogout} className={styles.logoutButton}>
          Sign out
        </button>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

export default ThatPlaceAdminLayout;
