/**
 * AuthContext — manages JWT tokens, authentication state, and current user profile.
 *
 * After login, fetches /api/v1/auth/me/ to populate user info (including
 * is_fieldmouse_admin) so the app can render the correct layout.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import api from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => !!localStorage.getItem('access_token'),
  );
  const [user, setUser] = useState(null);

  // On mount, if tokens exist, fetch user profile
  useEffect(() => {
    if (isAuthenticated && !user) {
      api.get('/api/v1/auth/me/')
        .then((r) => setUser(r.data))
        .catch(() => {
          // Token may have expired — clear session
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          setIsAuthenticated(false);
        });
    }
  }, [isAuthenticated, user]);

  const login = useCallback(async (email, password) => {
    const response = await api.post('/api/v1/auth/login/', { email, password });
    localStorage.setItem('access_token', response.data.access);
    localStorage.setItem('refresh_token', response.data.refresh);
    setIsAuthenticated(true);
    // Fetch user profile immediately after login
    const meResponse = await api.get('/api/v1/auth/me/');
    setUser(meResponse.data);
    return meResponse.data;
  }, []);

  const acceptInvite = useCallback(async (token, firstName, lastName, password) => {
    const response = await api.post('/api/v1/auth/accept-invite/', {
      token,
      first_name: firstName,
      last_name: lastName,
      password,
    });
    localStorage.setItem('access_token', response.data.access);
    localStorage.setItem('refresh_token', response.data.refresh);
    setIsAuthenticated(true);
    const meResponse = await api.get('/api/v1/auth/me/');
    setUser(meResponse.data);
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = localStorage.getItem('refresh_token');
    try {
      if (refreshToken) {
        await api.post('/api/v1/auth/logout/', { refresh: refreshToken });
      }
    } catch {
      // Proceed with local logout even if the server call fails
    } finally {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      setIsAuthenticated(false);
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, acceptInvite, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

AuthProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
