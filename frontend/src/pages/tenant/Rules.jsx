/**
 * Rule list page — Tenant Admin only.
 *
 * Lists all rules for the tenant. Admins can enable/disable, edit, and delete.
 * Clicking a row navigates to the rule detail page.
 * Ref: SPEC.md § Feature: Rules Engine
 */
import { useState } from 'react';
import PropTypes from 'prop-types';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDeleteRule, usePatchRule, useRules } from '../../hooks/useRules';
import styles from '../admin/AdminPage.module.css';
import ruleStyles from './Rules.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Active toggle
// ---------------------------------------------------------------------------

function ActiveToggle({ rule, canEdit }) {
  /**
   * Clickable pill that PATCHes is_active on the rule.
   * For non-admins renders as a static badge.
   */
  const patchRule = usePatchRule();
  const [loading, setLoading] = useState(false);

  const handleToggle = async (e) => {
    e.stopPropagation();
    setLoading(true);
    try {
      await patchRule.mutateAsync({ ruleId: rule.id, data: { is_active: !rule.is_active } });
    } finally {
      setLoading(false);
    }
  };

  if (!canEdit) {
    return (
      <span className={rule.is_active ? styles.badgeActive : styles.badgeInactive}>
        {rule.is_active ? 'Active' : 'Inactive'}
      </span>
    );
  }

  return (
    <button
      onClick={handleToggle}
      disabled={loading}
      className={rule.is_active ? ruleStyles.toggleActive : ruleStyles.toggleInactive}
      title={rule.is_active ? 'Click to disable' : 'Click to enable'}
    >
      {loading ? '…' : rule.is_active ? 'Active' : 'Inactive'}
    </button>
  );
}

ActiveToggle.propTypes = {
  rule: PropTypes.object.isRequired,
  canEdit: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function Rules() {
  /**
   * Rule list with enable/disable toggle and admin actions.
   * Ref: SPEC.md § Feature: Rules Engine
   */
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.tenant_role === 'admin';

  const { data: rules = [], isLoading, isError } = useRules();
  const deleteRule = useDeleteRule();

  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState('');

  const handleDelete = async (e, rule) => {
    e.stopPropagation();
    if (!window.confirm(`Delete rule "${rule.name}"? This cannot be undone.`)) return;
    setDeletingId(rule.id);
    setError('');
    try {
      await deleteRule.mutateAsync(rule.id);
    } catch {
      setError('Failed to delete rule.');
    } finally {
      setDeletingId(null);
    }
  };

  if (isLoading) return <p className={styles.loading}>Loading rules…</p>;
  if (isError) return <p className={styles.error}>Failed to load rules.</p>;

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Rules</h1>
        {isAdmin && (
          <Link to="/app/rules/new" className={styles.primaryButton}>
            New rule
          </Link>
        )}
      </div>

      {error && <p className={styles.error} style={{ marginBottom: '1rem' }}>{error}</p>}

      {rules.length === 0 ? (
        <div className={styles.section}>
          <p className={styles.empty}>
            No rules yet.
            {isAdmin && ' Create a rule to start automating actions when conditions are met.'}
          </p>
        </div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Last fired</th>
              <th>Cooldown</th>
              {isAdmin && <th></th>}
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr
                key={rule.id}
                className={ruleStyles.ruleRow}
                onClick={() => navigate(`/app/rules/${rule.id}`)}
                style={{ cursor: 'pointer' }}
              >
                <td>
                  <span style={{ fontWeight: 600 }}>{rule.name}</span>
                  {rule.description && (
                    <span className={ruleStyles.description}>{rule.description}</span>
                  )}
                </td>
                <td>
                  <ActiveToggle rule={rule} canEdit={isAdmin} />
                </td>
                <td>{formatDateTime(rule.last_fired_at)}</td>
                <td>{rule.cooldown_minutes ? `${rule.cooldown_minutes} min` : '—'}</td>
                {isAdmin && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <Link
                        to={`/app/rules/${rule.id}/edit`}
                        className={styles.secondaryButton}
                        style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
                      >
                        Edit
                      </Link>
                      <button
                        onClick={(e) => handleDelete(e, rule)}
                        disabled={deletingId === rule.id}
                        className={styles.dangerButton}
                        style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
                      >
                        {deletingId === rule.id ? '…' : 'Delete'}
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default Rules;
