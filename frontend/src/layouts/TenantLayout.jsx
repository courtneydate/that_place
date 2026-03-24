/**
 * Layout wrapper for tenant user pages.
 *
 * Renders a top navigation bar and main content area for tenant-scoped pages.
 * Navigation links will grow each sprint as new pages are added.
 */
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import styles from './TenantLayout.module.css';

function TenantLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <span className={styles.brand}>That Place</span>
        <nav className={styles.nav}>
          <NavLink
            to="/app/dashboards"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Dashboards
          </NavLink>
          <NavLink
            to="/app/users"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Users
          </NavLink>
          <NavLink
            to="/app/sites"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Sites
          </NavLink>
          <NavLink
            to="/app/devices"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Devices
          </NavLink>
          <NavLink
            to="/app/groups"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Groups
          </NavLink>
          <NavLink
            to="/app/data-sources"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Data Sources
          </NavLink>
          <NavLink
            to="/app/settings"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Settings
          </NavLink>
        </nav>
        <div className={styles.headerRight}>
          {user && (
            <div className={styles.userInfo}>
              {user.tenant_name && (
                <span className={styles.tenantName}>{user.tenant_name}</span>
              )}
              <span className={styles.userEmail}>{user.email}</span>
            </div>
          )}
          <button onClick={handleLogout} className={styles.logoutButton}>
            Sign out
          </button>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

export default TenantLayout;
