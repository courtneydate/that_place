/**
 * Axios instance with JWT auth interceptors.
 *
 * - Attaches access token to every request via Authorization header.
 * - On 401, attempts a silent token refresh using the stored refresh token.
 * - On refresh failure, clears tokens and redirects to /login.
 *
 * Auth context (Sprint 1) builds on top of this service.
 */
import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // For FormData requests, remove the default Content-Type so the browser
  // sets it automatically with the correct multipart/form-data boundary.
  // Without this, the axios default 'application/json' Content-Type persists
  // and Django uses the JSON parser instead of MultiPartParser.
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const refreshToken = localStorage.getItem('refresh_token');
    const isLoginRequest = originalRequest.url?.includes('/auth/login/');
    if (error.response?.status === 401 && !originalRequest._retry && refreshToken && !isLoginRequest) {
      originalRequest._retry = true;
      try {
        const response = await axios.post(`${BASE_URL}/api/v1/auth/refresh/`, {
          refresh: refreshToken,
        });
        const { access } = response.data;
        localStorage.setItem('access_token', access);
        originalRequest.headers.Authorization = `Bearer ${access}`;
        return api(originalRequest);
      } catch {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        if (!window.location.pathname.startsWith('/login')) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.replace(`/login?next=${next}`);
        }
      }
    }
    return Promise.reject(error);
  },
);

export default api;
