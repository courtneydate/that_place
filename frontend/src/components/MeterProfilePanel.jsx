/**
 * MeterProfilePanel — Sprint 29.
 *
 * Renders the meter-profile sidecar on the Device Detail page. When the
 * device has no profile yet, shows a "Mark as billing meter" button; once a
 * profile exists, lets the Tenant Admin edit NMI, role, parent gate meter,
 * phases, install date, pattern approval, and secondary serial. Backend
 * write-time invariants surface as field-level errors (e.g. picking a child
 * role on a hierarchical site without a parent).
 *
 * Read access is open to all tenant users; writes require Tenant Admin —
 * the parent enforces this by passing `canEdit`.
 *
 * Ref: SPEC.md § Feature: Metering Model — Meter Profiles
 *      ROADMAP.md § Sprint 29
 */
import { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import {
  useMeterProfile,
  useSaveMeterProfile,
  useDeleteMeterProfile,
} from '../hooks/useMeterProfiles';
import { useDevices } from '../hooks/useDevices';
import styles from '../pages/admin/AdminPage.module.css';

const METER_ROLES = [
  { value: 'gate', label: 'Gate (embedded-network parent)' },
  { value: 'child', label: 'Child (embedded-network tenant)' },
  { value: 'generation', label: 'Generation (solar revenue)' },
  { value: 'storage', label: 'Storage (BESS)' },
  { value: 'consumption', label: 'Consumption (single-tier host)' },
  { value: 'common_area', label: 'Common area / landlord' },
  { value: 'sub_check', label: 'Sub-check (informational)' },
];

const PARENT_REQUIRED_ROLES = new Set(['child', 'common_area']);
const PARENT_FORBIDDEN_ROLES = new Set([
  'gate', 'generation', 'storage', 'consumption', 'sub_check',
]);

function fieldErrors(err) {
  const details = err?.response?.data?.error?.details;
  if (!details || typeof details !== 'object') return {};
  return Object.fromEntries(
    Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v)]),
  );
}

function topLevelMessage(err) {
  return err?.response?.data?.error?.message || 'Save failed.';
}

function MeterProfilePanel({ device, canEdit }) {
  const deviceId = device?.id;
  const { data: profile, isLoading, isError } = useMeterProfile(deviceId);
  const saveProfile = useSaveMeterProfile(deviceId);
  const deleteProfile = useDeleteMeterProfile(deviceId);
  const { data: devices = [] } = useDevices();

  // Only show gate meters on the same site as candidate parents. We don't
  // have a dedicated /meters endpoint yet, so we infer "is gate meter" from
  // the parent-meter-serial field other profiles expose; safer approach for
  // v1 is to let the operator pick any device on the same site and rely on
  // the backend invariant to surface a clear error if the choice isn't a
  // gate. The dropdown still trims to same-site to keep the list short.
  const sameSiteDevices = useMemo(
    () => devices.filter((d) => d.site === device?.site && d.id !== deviceId),
    [devices, device?.site, deviceId],
  );

  if (!device) return null;
  if (isLoading) return <p className={styles.loading}>Loading meter profile…</p>;
  if (isError) return <p className={styles.error}>Failed to load meter profile.</p>;

  // No profile yet — show CTA (Admin) or info text (everyone else).
  if (!profile) {
    if (!canEdit) {
      return (
        <p className={styles.empty}>
          This device is not configured as a billing meter.
        </p>
      );
    }
    return (
      <ProfileForm
        deviceId={deviceId}
        device={device}
        sameSiteDevices={sameSiteDevices}
        mode="create"
        initial={null}
        saveProfile={saveProfile}
      />
    );
  }

  return (
    <ProfileForm
      deviceId={deviceId}
      device={device}
      sameSiteDevices={sameSiteDevices}
      mode={canEdit ? 'edit' : 'view'}
      initial={profile}
      saveProfile={saveProfile}
      deleteProfile={deleteProfile}
    />
  );
}

MeterProfilePanel.propTypes = {
  device: PropTypes.object,
  canEdit: PropTypes.bool.isRequired,
};

function ProfileForm({
  deviceId,
  device,
  sameSiteDevices,
  mode,
  initial,
  saveProfile,
  deleteProfile,
}) {
  const isView = mode === 'view';
  const isCreate = mode === 'create';

  const [meterRole, setMeterRole] = useState(initial?.meter_role || '');
  const [nmi, setNmi] = useState(initial?.nmi || '');
  const [parentMeter, setParentMeter] = useState(initial?.parent_meter || '');
  const [phases, setPhases] = useState(initial?.phases || 1);
  const [installDate, setInstallDate] = useState(initial?.install_date || '');
  const [patternApproval, setPatternApproval] = useState(initial?.pattern_approval || '');
  const [secondarySerial, setSecondarySerial] = useState(initial?.serial_number_secondary || '');
  const [errors, setErrors] = useState({});
  const [topError, setTopError] = useState('');
  const [success, setSuccess] = useState('');

  const parentRequired = PARENT_REQUIRED_ROLES.has(meterRole) && device.site_is_hierarchical;
  const parentForbidden = PARENT_FORBIDDEN_ROLES.has(meterRole);

  const handleRoleChange = (value) => {
    setMeterRole(value);
    if (PARENT_FORBIDDEN_ROLES.has(value)) {
      setParentMeter('');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrors({});
    setTopError('');
    setSuccess('');
    if (!meterRole) {
      setErrors({ meter_role: 'Role is required.' });
      return;
    }
    const payload = {
      meter_role: meterRole,
      nmi: nmi.trim() || null,
      parent_meter: parentMeter ? Number(parentMeter) : null,
      phases: Number(phases),
      install_date: installDate || null,
      pattern_approval: patternApproval.trim(),
      serial_number_secondary: secondarySerial.trim(),
    };
    try {
      await saveProfile.mutateAsync(payload);
      setSuccess(isCreate ? 'Meter profile created.' : 'Saved.');
    } catch (err) {
      setErrors(fieldErrors(err));
      setTopError(topLevelMessage(err));
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Remove the meter profile from this device?')) return;
    setTopError('');
    setSuccess('');
    try {
      await deleteProfile.mutateAsync();
      setSuccess('Meter profile removed.');
      // Reset local state so the create form shows next render
      setMeterRole('');
      setNmi('');
      setParentMeter('');
      setPhases(1);
      setInstallDate('');
      setPatternApproval('');
      setSecondarySerial('');
    } catch (err) {
      setTopError(topLevelMessage(err));
    }
  };

  const renderField = (label, htmlFor, input, hint, error) => (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={htmlFor}>{label}</label>
      {input}
      {hint && <small style={{ color: '#6B7280' }}>{hint}</small>}
      {error && <p className={styles.error} style={{ margin: '0.25rem 0 0' }}>{error}</p>}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className={styles.form} noValidate>
      <p style={{ fontSize: '0.8125rem', color: '#6B7280', marginBottom: '0.5rem' }}>
        Site is {device.site_name}{device.site_is_hierarchical
          ? <strong> · hierarchical</strong>
          : ' · flat'}.
      </p>
      <div className={styles.inlineFields}>
        {renderField(
          'Role *',
          `mp-role-${deviceId}`,
          <select
            id={`mp-role-${deviceId}`}
            value={meterRole}
            onChange={(e) => handleRoleChange(e.target.value)}
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          >
            <option value="">— Select role —</option>
            {METER_ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>,
          null,
          errors.meter_role,
        )}
        {renderField(
          'NMI',
          `mp-nmi-${deviceId}`,
          <input
            id={`mp-nmi-${deviceId}`}
            type="text"
            value={nmi}
            onChange={(e) => setNmi(e.target.value)}
            placeholder="10/11 digit NMI"
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          />,
          'Unique per tenant when set.',
          errors.nmi,
        )}
        {renderField(
          'Phases',
          `mp-phases-${deviceId}`,
          <select
            id={`mp-phases-${deviceId}`}
            value={phases}
            onChange={(e) => setPhases(Number(e.target.value))}
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          >
            <option value={1}>Single phase</option>
            <option value={3}>Three phase</option>
          </select>,
          null,
          errors.phases,
        )}
      </div>
      <div className={styles.inlineFields}>
        {renderField(
          parentRequired ? 'Parent gate meter *' : 'Parent gate meter',
          `mp-parent-${deviceId}`,
          <select
            id={`mp-parent-${deviceId}`}
            value={parentMeter}
            onChange={(e) => setParentMeter(e.target.value)}
            disabled={isView || saveProfile.isPending || parentForbidden}
            className={styles.input}
          >
            <option value="">— None —</option>
            {sameSiteDevices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.serial_number})
              </option>
            ))}
          </select>,
          parentForbidden
            ? 'Not applicable for this role.'
            : parentRequired
              ? 'Required on hierarchical sites for child / common-area meters.'
              : 'Optional on a flat site.',
          errors.parent_meter,
        )}
        {renderField(
          'Install date',
          `mp-install-${deviceId}`,
          <input
            id={`mp-install-${deviceId}`}
            type="date"
            value={installDate}
            onChange={(e) => setInstallDate(e.target.value)}
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          />,
          null,
          errors.install_date,
        )}
        {renderField(
          'Pattern approval',
          `mp-pattern-${deviceId}`,
          <input
            id={`mp-pattern-${deviceId}`}
            type="text"
            value={patternApproval}
            onChange={(e) => setPatternApproval(e.target.value)}
            placeholder="e.g. NMI-M6"
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          />,
          'Surfaces on invoice footers / audit reports.',
          errors.pattern_approval,
        )}
      </div>
      <div className={styles.inlineFields}>
        {renderField(
          'Secondary serial',
          `mp-serial2-${deviceId}`,
          <input
            id={`mp-serial2-${deviceId}`}
            type="text"
            value={secondarySerial}
            onChange={(e) => setSecondarySerial(e.target.value)}
            placeholder="e.g. CET PMC serial"
            disabled={isView || saveProfile.isPending}
            className={styles.input}
          />,
          'For bundled-meter cases (e.g. WW 6M+One).',
          errors.serial_number_secondary,
        )}
      </div>
      {!isView && (
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={saveProfile.isPending}
          >
            {saveProfile.isPending
              ? 'Saving…'
              : isCreate ? 'Create meter profile' : 'Save changes'}
          </button>
          {!isCreate && deleteProfile && (
            <button
              type="button"
              className={styles.dangerButton}
              onClick={handleDelete}
              disabled={deleteProfile.isPending}
            >
              {deleteProfile.isPending ? 'Removing…' : 'Remove meter profile'}
            </button>
          )}
        </div>
      )}
      {topError && <p className={styles.error}>{topError}</p>}
      {success && <p style={{ color: '#22C55E', fontSize: '0.875rem' }}>{success}</p>}
    </form>
  );
}

ProfileForm.propTypes = {
  deviceId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  device: PropTypes.object.isRequired,
  sameSiteDevices: PropTypes.array.isRequired,
  mode: PropTypes.oneOf(['view', 'edit', 'create']).isRequired,
  initial: PropTypes.object,
  saveProfile: PropTypes.object.isRequired,
  deleteProfile: PropTypes.object,
};

export default MeterProfilePanel;
