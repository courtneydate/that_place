/**
 * Billing Schedules management page (Sprint 32).
 *
 * Route: /app/billing-schedules
 * Tenant Admin only. Lists active schedules; create/edit form with cadence
 * picker, anchor_day (monthly_anchor only), period_offset_days, and
 * auto_finalize toggle.
 *
 * Ref: SPEC.md § Feature: Billing Runs & Invoicing — BillingSchedule
 *      ROADMAP.md § Sprint 32
 */
import PropTypes from 'prop-types';
import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSites } from '../../hooks/useSites';
import {
  useBillingSchedules,
  useCreateBillingSchedule,
  useDeleteBillingSchedule,
  useUpdateBillingSchedule,
} from '../../hooks/useBillingRuns';
import styles from '../admin/AdminPage.module.css';

const CADENCE_LABELS = {
  monthly_calendar: 'Monthly (calendar month)',
  monthly_anchor:   'Monthly (anchor day)',
  quarterly:        'Quarterly (calendar)',
  custom_cron:      'Custom cron',
};

const AGGREGATE_LABELS = {
  '5min':  '5 minutes',
  '30min': '30 minutes',
  '1h':    '1 hour',
};

function fmt(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Schedule form (create + edit)
// ---------------------------------------------------------------------------

function ScheduleForm({ initial = {}, onSave, onCancel }) {
  const { data: sites = [] } = useSites();
  const createSchedule = useCreateBillingSchedule();
  const updateSchedule = useUpdateBillingSchedule(initial.id);

  const [name, setName] = useState(initial.name || '');
  const [siteId, setSiteId] = useState(initial.site || '');
  const [cadence, setCadence] = useState(initial.cadence || 'monthly_calendar');
  const [anchorDay, setAnchorDay] = useState(initial.anchor_day ?? '');
  const [periodOffset, setPeriodOffset] = useState(initial.period_offset_days ?? 0);
  const [aggregatePeriod, setAggregatePeriod] = useState(initial.aggregate_period || '30min');
  const [autoFinalize, setAutoFinalize] = useState(initial.auto_finalize ?? false);
  const [isActive, setIsActive] = useState(initial.is_active !== false);
  const [customCron, setCustomCron] = useState(initial.custom_cron || '');
  const [error, setError] = useState('');

  const isEdit = Boolean(initial.id);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim() || !siteId) {
      setError('Name and site are required.');
      return;
    }
    if (cadence === 'monthly_anchor' && !anchorDay) {
      setError('Anchor day is required for monthly anchor cadence.');
      return;
    }
    if (cadence === 'custom_cron' && !customCron.trim()) {
      setError('Cron expression is required for custom cron cadence.');
      return;
    }

    const payload = {
      name: name.trim(),
      site: siteId,
      cadence,
      anchor_day: cadence === 'monthly_anchor' ? Number(anchorDay) : null,
      period_offset_days: Number(periodOffset),
      aggregate_period: aggregatePeriod,
      auto_finalize: autoFinalize,
      is_active: isActive,
      custom_cron: cadence === 'custom_cron' ? customCron.trim() : '',
    };

    try {
      if (isEdit) {
        await updateSchedule.mutateAsync(payload);
      } else {
        await createSchedule.mutateAsync(payload);
      }
      onSave();
    } catch (err) {
      const detail = err.response?.data;
      if (typeof detail === 'object' && !detail.error) {
        const msgs = Object.entries(detail).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`);
        setError(msgs.join(' | '));
      } else {
        setError(detail?.error?.message || 'Failed to save schedule.');
      }
    }
  };

  const isPending = createSchedule.isPending || updateSchedule.isPending;

  return (
    <div className={styles.section}>
      <h2 className={styles.sectionTitle}>{isEdit ? 'Edit schedule' : 'New billing schedule'}</h2>
      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label className={styles.label}>Name</label>
          <input
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Monthly PPA billing"
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label}>Site</label>
          <select
            className={styles.input}
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            required
          >
            <option value="">Select a site…</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>

        <div className={styles.inlineFields}>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label}>Cadence</label>
            <select
              className={styles.input}
              value={cadence}
              onChange={(e) => setCadence(e.target.value)}
            >
              {Object.entries(CADENCE_LABELS).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>

          {cadence === 'monthly_anchor' && (
            <div className={styles.field} style={{ width: 120 }}>
              <label className={styles.label}>Anchor day (1–31)</label>
              <input
                type="number"
                min={1}
                max={31}
                className={styles.input}
                value={anchorDay}
                onChange={(e) => setAnchorDay(e.target.value)}
                required
              />
            </div>
          )}
        </div>

        {cadence === 'custom_cron' && (
          <div className={styles.field}>
            <label className={styles.label}>Cron expression</label>
            <input
              className={styles.input}
              value={customCron}
              onChange={(e) => setCustomCron(e.target.value)}
              placeholder="0 0 1 * *"
              required
            />
            <span style={{ fontSize: '0.8125rem', color: '#6B7280' }}>
              Standard 5-field cron (minute hour day month weekday)
            </span>
          </div>
        )}

        <div className={styles.inlineFields}>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label}>Period offset (days)</label>
            <input
              type="number"
              min={0}
              className={styles.input}
              value={periodOffset}
              onChange={(e) => setPeriodOffset(e.target.value)}
            />
            <span style={{ fontSize: '0.8125rem', color: '#6B7280' }}>
              Days to wait after period ends before running
            </span>
          </div>

          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label}>Aggregate period</label>
            <select
              className={styles.input}
              value={aggregatePeriod}
              onChange={(e) => setAggregatePeriod(e.target.value)}
            >
              {Object.entries(AGGREGATE_LABELS).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem', fontWeight: 500 }}>
          <input
            type="checkbox"
            checked={autoFinalize}
            onChange={(e) => setAutoFinalize(e.target.checked)}
          />
          Auto-finalize — automatically finalize the run when computed
        </label>

        {isEdit && (
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem', fontWeight: 500 }}>
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            Active
          </label>
        )}

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.actions}>
          <button type="submit" className={styles.primaryButton} disabled={isPending}>
            {isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create schedule'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

ScheduleForm.propTypes = {
  initial: PropTypes.object,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Delete hook wrapper
// ---------------------------------------------------------------------------

function DeleteButton({ id }) {
  const del = useDeleteBillingSchedule(id);
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <>
        <button
          className={styles.dangerButton}
          style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
          disabled={del.isPending}
          onClick={() => del.mutate()}
        >
          {del.isPending ? 'Deleting…' : 'Confirm delete'}
        </button>
        <button
          className={styles.secondaryButton}
          style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
          onClick={() => setConfirming(false)}
        >
          Cancel
        </button>
      </>
    );
  }
  return (
    <button
      className={styles.dangerButton}
      style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
      onClick={() => setConfirming(true)}
    >
      Delete
    </button>
  );
}
DeleteButton.propTypes = { id: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BillingSchedules() {
  const { user } = useAuth();
  const isAdmin = user?.tenant_role === 'admin';

  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const { data: schedules = [], isLoading, isError } = useBillingSchedules();

  if (!isAdmin) {
    return <p className={styles.error}>Tenant Admin access required.</p>;
  }

  const openCreate = () => { setEditTarget(null); setShowForm(true); };
  const openEdit = (sched) => { setEditTarget(sched); setShowForm(true); };
  const closeForm = () => { setShowForm(false); setEditTarget(null); };

  return (
    <div>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Billing Schedules</h1>
        {!showForm && (
          <button className={styles.primaryButton} onClick={openCreate}>
            New schedule
          </button>
        )}
      </div>

      {showForm && (
        <ScheduleForm
          initial={editTarget || {}}
          onSave={closeForm}
          onCancel={closeForm}
        />
      )}

      <div className={styles.section}>
        {isLoading && <p className={styles.loading}>Loading…</p>}
        {isError && <p className={styles.error}>Failed to load schedules.</p>}

        {!isLoading && !isError && schedules.length === 0 && (
          <p className={styles.empty}>No billing schedules configured.</p>
        )}

        {schedules.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Site</th>
                <th>Cadence</th>
                <th>Offset (days)</th>
                <th>Aggregate</th>
                <th>Auto-finalize</th>
                <th>Active</th>
                <th>Next run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((sched) => (
                <tr key={sched.id}>
                  <td style={{ fontWeight: 500 }}>{sched.name}</td>
                  <td>{sched.site_name || sched.site}</td>
                  <td>{CADENCE_LABELS[sched.cadence] || sched.cadence}</td>
                  <td className={styles.mono}>{sched.period_offset_days}</td>
                  <td className={styles.mono}>{AGGREGATE_LABELS[sched.aggregate_period] || sched.aggregate_period}</td>
                  <td>
                    <span className={sched.auto_finalize ? styles.badgeActive : styles.badgeInactive}>
                      {sched.auto_finalize ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td>
                    <span className={sched.is_active ? styles.badgeActive : styles.badgeInactive}>
                      {sched.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.8125rem' }}>{fmt(sched.next_run_at)}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        className={styles.secondaryButton}
                        style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
                        onClick={() => openEdit(sched)}
                      >
                        Edit
                      </button>
                      <DeleteButton id={sched.id} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
