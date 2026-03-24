/**
 * Semantic colour tokens for the That Place design system.
 *
 * RULE: Always use these tokens in components — never hardcode hex values.
 * All device status colours, alert state colours, and UI colours live here.
 */
export const colors = {
  brand: {
    primary: '#1A6B4A',
    primaryHover: '#155A3D',
    secondary: '#2E9E6B',
  },
  status: {
    online: '#22C55E',
    degraded: '#F59E0B',
    critical: '#EF4444',
    offline: '#6B7280',
    unknown: '#9CA3AF',
  },
  alert: {
    active: '#EF4444',
    acknowledged: '#F59E0B',
    resolved: '#22C55E',
  },
  neutral: {
    50: '#F9FAFB',
    100: '#F3F4F6',
    200: '#E5E7EB',
    300: '#D1D5DB',
    400: '#9CA3AF',
    500: '#6B7280',
    600: '#4B5563',
    700: '#374151',
    800: '#1F2937',
    900: '#111827',
  },
  surface: {
    background: '#F9FAFB',
    card: '#FFFFFF',
    border: '#E5E7EB',
    divider: '#F3F4F6',
  },
  text: {
    primary: '#111827',
    secondary: '#6B7280',
    disabled: '#9CA3AF',
    inverse: '#FFFFFF',
  },
};
