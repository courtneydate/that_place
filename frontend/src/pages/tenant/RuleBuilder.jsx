/**
 * Rule builder — step-flow for creating and editing rules.
 *
 * Route: /app/rules/new (create) and /app/rules/:id/edit (edit)
 * Steps: Name & Settings → Schedule Gate → Conditions → Actions → Review & Save
 * Tenant Admin only.
 * Ref: SPEC.md § Feature: Rules Engine, § UI/UX Notes — Rule Builder
 */
import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useCreateRule, useRule, useUpdateRule } from '../../hooks/useRules';
import { useDevices } from '../../hooks/useDevices';
import { useDeviceStreams, useStream } from '../../hooks/useStreams';
import { useDeviceTypes } from '../../hooks/useDeviceTypes';
import { useGroups } from '../../hooks/useGroups';
import { useUsers } from '../../hooks/useUsers';
import {
  useFeedProviderChannels,
  useFeedProviders,
  useReferenceDatasets,
} from '../../hooks/useFeeds';
import styles from '../admin/AdminPage.module.css';
import b from './RuleBuilder.module.css';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = ['Name & Settings', 'Schedule Gate', 'Conditions', 'Actions', 'Review & Save'];

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKEND = [5, 6];
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

const OPERATORS_BY_TYPE = {
  numeric: ['>', '<', '>=', '<=', '==', '!='],
  boolean: ['=='],
  string: ['==', '!='],
};

const OPERATOR_LABELS = {
  '>': '> greater than',
  '<': '< less than',
  '>=': '>= greater than or equal',
  '<=': '<= less than or equal',
  '==': '== equals',
  '!=': '!= not equals',
};

const TEMPLATE_VARS = [
  '{{device_name}}', '{{stream_name}}', '{{value}}', '{{unit}}',
  '{{triggered_at}}', '{{rule_name}}', '{{site_name}}',
];

const CHANNELS = [
  { key: 'in_app', label: 'In-app' },
  { key: 'email', label: 'Email' },
  { key: 'sms', label: 'SMS' },
  { key: 'push', label: 'Push' },
];

// ---------------------------------------------------------------------------
// Form defaults
// ---------------------------------------------------------------------------

const emptyCondition = (order = 0) => ({
  condition_type: 'stream',
  stream: null,
  _device_id: null,
  operator: '',
  threshold_value: '',
  staleness_minutes: '',
  channel: null,
  _provider_id: null,
  dataset: null,
  value_key: '',
  dimension_overrides: null,
  order,
});

const emptyGroup = (order = 0) => ({
  logical_operator: 'AND',
  order,
  conditions: [emptyCondition(0)],
});

const emptyAction = () => ({
  action_type: 'notify',
  notification_channels: ['in_app', 'email'],
  group_ids: [],
  user_ids: [],
  message_template: '',
  target_device: null,
  command: null,
});

const defaultForm = () => ({
  name: '',
  description: '',
  is_active: true,
  cooldown_minutes: '',
  active_days: [],
  active_from: '',
  active_to: '',
  condition_group_operator: 'AND',
  condition_groups: [emptyGroup(0)],
  actions: [emptyAction()],
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Strip time to HH:MM for <input type="time" /> */
const toTimeInput = (t) => (t ? String(t).slice(0, 5) : '');

/** Build the API payload from form state, stripping UI-only (_) fields. */
const buildPayload = (form) => ({
  name: form.name.trim(),
  description: form.description.trim(),
  is_active: form.is_active,
  cooldown_minutes: form.cooldown_minutes !== '' ? parseInt(form.cooldown_minutes, 10) : null,
  active_days: form.active_days.length > 0 ? form.active_days : null,
  active_from: form.active_from || null,
  active_to: form.active_to || null,
  condition_group_operator: form.condition_group_operator,
  condition_groups: form.condition_groups.map((g, gi) => ({
    logical_operator: g.logical_operator,
    order: gi,
    conditions: g.conditions.map((c, ci) => {
      const base = { condition_type: c.condition_type, order: ci };
      if (c.condition_type === 'stream') {
        return { ...base, stream: c.stream, operator: c.operator, threshold_value: c.threshold_value };
      }
      if (c.condition_type === 'staleness') {
        return { ...base, stream: c.stream, staleness_minutes: parseInt(c.staleness_minutes, 10) };
      }
      if (c.condition_type === 'feed_channel') {
        return { ...base, channel: c.channel, operator: c.operator, threshold_value: c.threshold_value };
      }
      // reference_value
      return {
        ...base,
        dataset: c.dataset,
        value_key: c.value_key,
        operator: c.operator,
        threshold_value: c.threshold_value,
        dimension_overrides: c.dimension_overrides || null,
      };
    }),
  })),
  actions: form.actions.map((a) => {
    if (a.action_type === 'notify') {
      return {
        action_type: 'notify',
        notification_channels: a.notification_channels,
        group_ids: a.group_ids,
        user_ids: a.user_ids,
        message_template: a.message_template,
      };
    }
    return {
      action_type: 'command',
      target_device: a.target_device,
      command: a.command,
    };
  }),
});

/** Initialise form state from an existing rule (edit mode). */
const formFromRule = (rule) => ({
  name: rule.name || '',
  description: rule.description || '',
  is_active: rule.is_active ?? true,
  cooldown_minutes: rule.cooldown_minutes != null ? String(rule.cooldown_minutes) : '',
  active_days: rule.active_days || [],
  active_from: toTimeInput(rule.active_from),
  active_to: toTimeInput(rule.active_to),
  condition_group_operator: rule.condition_group_operator || 'AND',
  condition_groups: rule.condition_groups?.length > 0
    ? rule.condition_groups.map((g, gi) => ({
        logical_operator: g.logical_operator || 'AND',
        order: g.order ?? gi,
        conditions: (g.conditions || []).map((c, ci) => ({
          condition_type: c.condition_type || 'stream',
          stream: c.stream || null,
          _device_id: null,           // resolved lazily by StreamPicker
          operator: c.operator || '',
          threshold_value: c.threshold_value != null ? String(c.threshold_value) : '',
          staleness_minutes: c.staleness_minutes != null ? String(c.staleness_minutes) : '',
          channel: c.channel || null,
          _provider_id: null,
          dataset: c.dataset || null,
          value_key: c.value_key || '',
          dimension_overrides: c.dimension_overrides || null,
          order: c.order ?? ci,
        })),
      }))
    : [emptyGroup(0)],
  actions: rule.actions?.length > 0
    ? rule.actions.map((a) => ({
        action_type: a.action_type || 'notify',
        notification_channels: a.notification_channels || ['in_app', 'email'],
        group_ids: a.group_ids || [],
        user_ids: a.user_ids || [],
        message_template: a.message_template || '',
        target_device: a.target_device || null,
        command: a.command || null,
      }))
    : [emptyAction()],
});

/** Validate per-step before advancing. */
const validateStep = (step, form) => {
  if (step === 1) {
    if (!form.name.trim()) return 'Rule name is required.';
  }
  if (step === 2) {
    if ((form.active_from && !form.active_to) || (!form.active_from && form.active_to)) {
      return 'Set both From and To times, or neither.';
    }
  }
  if (step === 3) {
    if (form.condition_groups.length === 0) return 'Add at least one condition group.';
    for (const g of form.condition_groups) {
      if (g.conditions.length === 0) return 'Each group needs at least one condition.';
      for (const c of g.conditions) {
        if (c.condition_type === 'stream') {
          if (!c.stream) return 'Select a stream for every stream condition.';
          if (!c.operator) return 'Select an operator for every stream condition.';
          if (c.threshold_value === '') return 'Enter a value for every stream condition.';
        } else if (c.condition_type === 'staleness') {
          if (!c.stream) return 'Select a stream for every staleness condition.';
          if (!c.staleness_minutes || parseInt(c.staleness_minutes, 10) < 2) {
            return 'Staleness threshold must be at least 2 minutes.';
          }
        } else if (c.condition_type === 'feed_channel') {
          if (!c.channel) return 'Select a feed channel for every feed_channel condition.';
          if (!c.operator) return 'Select an operator for every feed_channel condition.';
          if (c.threshold_value === '') return 'Enter a value for every feed_channel condition.';
        } else if (c.condition_type === 'reference_value') {
          if (!c.dataset) return 'Select a dataset for every reference_value condition.';
          if (!c.value_key) return 'Select a value key for every reference_value condition.';
          if (!c.operator) return 'Select an operator for every reference_value condition.';
          if (c.threshold_value === '') return 'Enter a value for every reference_value condition.';
        }
      }
    }
  }
  if (step === 4) {
    if (form.actions.length === 0) return 'Add at least one action.';
    for (const a of form.actions) {
      if (a.action_type === 'notify') {
        if (a.notification_channels.length === 0) return 'Select at least one notification channel.';
        if (!a.message_template.trim()) return 'Enter a message template.';
      }
      if (a.action_type === 'command') {
        if (!a.target_device) return 'Select a target device for the command action.';
        if (!a.command?.name) return 'Select a command for the command action.';
      }
    }
  }
  return null;
};

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

function StepBar({ current }) {
  /**
   * Visual step indicator showing progress through the builder.
   */
  return (
    <ol className={b.stepBar}>
      {STEPS.map((label, i) => {
        const n = i + 1;
        const isDone = n < current;
        const isActive = n === current;
        return (
          <li
            key={label}
            className={`${b.stepItem} ${isDone ? b.stepDone : ''} ${isActive ? b.stepActive : ''}`}
          >
            {i > 0 && <span className={b.stepConnector} />}
            <span className={b.stepNumber}>{isDone ? '✓' : n}</span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

StepBar.propTypes = { current: PropTypes.number.isRequired };

// ---------------------------------------------------------------------------
// Operator toggle (AND / OR)
// ---------------------------------------------------------------------------

function OperatorToggle({ value, onChange }) {
  /**
   * Two-button toggle for AND / OR combinator selection.
   */
  return (
    <div className={b.operatorToggle}>
      {['AND', 'OR'].map((op) => (
        <button
          key={op}
          type="button"
          onClick={() => onChange(op)}
          className={`${b.operatorBtn} ${value === op ? b.operatorBtnActive : ''}`}
        >
          {op}
        </button>
      ))}
    </div>
  );
}

OperatorToggle.propTypes = {
  value: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Stream picker — site → device → stream cascade
// ---------------------------------------------------------------------------

function StreamPicker({ streamId, deviceId, onChangeStream, devices }) {
  /**
   * Cascading selects: device (grouped by site) → stream.
   *
   * When editing and deviceId is null but streamId is set, fetches stream
   * detail to resolve which device the stream belongs to, then calls
   * onChangeStream so the parent can update _device_id.
   */
  const needsDeviceLookup = !!streamId && !deviceId;
  const { data: streamDetail } = useStream(needsDeviceLookup ? streamId : null);

  const resolvedDeviceId = deviceId || streamDetail?.device || null;
  const { data: streams = [], isLoading: streamsLoading } = useDeviceStreams(resolvedDeviceId);

  // Once we resolve the device via stream detail, propagate it up once.
  useEffect(() => {
    if (streamDetail && !deviceId) {
      onChangeStream({ stream: streamId, _device_id: streamDetail.device, _data_type: streamDetail.data_type });
    }
  }, [streamDetail, deviceId, streamId, onChangeStream]);

  const handleDeviceChange = (e) => {
    const did = parseInt(e.target.value, 10) || null;
    onChangeStream({ stream: null, _device_id: did, _data_type: null });
  };

  const handleStreamChange = (e) => {
    const sid = parseInt(e.target.value, 10) || null;
    const s = streams.find((x) => x.id === sid);
    onChangeStream({ stream: sid, _device_id: resolvedDeviceId, _data_type: s?.data_type || null });
  };

  // Group active devices by site name for the optgroup hierarchy.
  const bySite = {};
  for (const d of devices) {
    if (d.status !== 'active') continue;
    const sn = d.site_name || 'No site';
    if (!bySite[sn]) bySite[sn] = [];
    bySite[sn].push(d);
  }

  return (
    <>
      <select
        className={b.selectSmall}
        value={resolvedDeviceId || ''}
        onChange={handleDeviceChange}
        style={{ minWidth: '160px' }}
      >
        <option value="">Device…</option>
        {Object.entries(bySite).map(([siteName, siteDevices]) => (
          <optgroup key={siteName} label={siteName}>
            {siteDevices.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </optgroup>
        ))}
      </select>
      {resolvedDeviceId && (
        <select
          className={b.selectSmall}
          value={streamId || ''}
          onChange={handleStreamChange}
          disabled={streamsLoading}
          style={{ minWidth: '160px' }}
        >
          <option value="">Stream…</option>
          {streams.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label || s.key} ({s.data_type})
            </option>
          ))}
        </select>
      )}
    </>
  );
}

StreamPicker.propTypes = {
  streamId: PropTypes.number,
  deviceId: PropTypes.number,
  onChangeStream: PropTypes.func.isRequired,
  devices: PropTypes.array.isRequired,
};

// ---------------------------------------------------------------------------
// Feed channel picker — provider → channel cascade
// ---------------------------------------------------------------------------

function FeedChannelPicker({ channelId, providerId, onChangeChannel }) {
  /**
   * Two-step cascade: pick provider (system-scope) → pick channel.
   * Shows latest reading value as a hint when available.
   */
  const { data: providersData } = useFeedProviders();
  const { data: channelsData, isLoading: loadingChannels } = useFeedProviderChannels(providerId);

  const providers = Array.isArray(providersData)
    ? providersData.filter((p) => p.scope === 'system')
    : (providersData?.results ?? []).filter((p) => p.scope === 'system');
  const channels = Array.isArray(channelsData) ? channelsData : (channelsData?.results ?? []);
  const selected = channels.find((c) => c.id === channelId);

  return (
    <>
      <select
        className={b.selectSmall}
        value={providerId || ''}
        onChange={(e) => onChangeChannel({ channel: null, _provider_id: parseInt(e.target.value, 10) || null })}
        style={{ minWidth: '160px' }}
      >
        <option value="">Provider…</option>
        {providers.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      {providerId && (
        <select
          className={b.selectSmall}
          value={channelId || ''}
          onChange={(e) => onChangeChannel({ channel: parseInt(e.target.value, 10) || null, _provider_id: providerId })}
          disabled={loadingChannels}
          style={{ minWidth: '180px' }}
        >
          <option value="">Channel…</option>
          {channels.map((ch) => (
            <option key={ch.id} value={ch.id}>
              {ch.label || ch.key}
              {ch.dimension_value ? ` [${ch.dimension_value}]` : ''}
              {' '}({ch.unit || ch.data_type})
            </option>
          ))}
        </select>
      )}

      {selected?.latest_reading && (
        <span style={{ fontSize: '0.8125rem', color: '#6B7280', whiteSpace: 'nowrap' }}>
          Last: <strong>{selected.latest_reading.value}</strong> {selected.unit}
        </span>
      )}
    </>
  );
}

FeedChannelPicker.propTypes = {
  channelId: PropTypes.number,
  providerId: PropTypes.number,
  onChangeChannel: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Reference value picker — dataset → value key
// ---------------------------------------------------------------------------

function ReferenceValuePicker({ datasetId, valueKey, onChangeDataset }) {
  /**
   * Selects a dataset then the value key to compare.
   * Shows the schema-defined value keys from the selected dataset.
   */
  const { data: datasetsData } = useReferenceDatasets();
  const datasets = Array.isArray(datasetsData) ? datasetsData : (datasetsData?.results ?? []);
  const selectedDataset = datasets.find((d) => d.id === datasetId);
  const valueKeys = selectedDataset ? Object.keys(selectedDataset.value_schema || {}) : [];

  return (
    <>
      <select
        className={b.selectSmall}
        value={datasetId || ''}
        onChange={(e) => onChangeDataset({ dataset: parseInt(e.target.value, 10) || null, value_key: '' })}
        style={{ minWidth: '180px' }}
      >
        <option value="">Dataset…</option>
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>

      {datasetId && (
        <select
          className={b.selectSmall}
          value={valueKey || ''}
          onChange={(e) => onChangeDataset({ dataset: datasetId, value_key: e.target.value })}
          style={{ minWidth: '160px' }}
        >
          <option value="">Value key…</option>
          {valueKeys.map((k) => {
            const def = selectedDataset.value_schema[k] || {};
            return (
              <option key={k} value={k}>
                {def.label || k}{def.unit ? ` (${def.unit})` : ''}
              </option>
            );
          })}
        </select>
      )}

      {selectedDataset?.has_time_of_use && (
        <span style={{ fontSize: '0.8125rem', color: '#6B7280', whiteSpace: 'nowrap' }}>
          TOU — resolved from assignment at eval time
        </span>
      )}
    </>
  );
}

ReferenceValuePicker.propTypes = {
  datasetId: PropTypes.number,
  valueKey: PropTypes.string,
  onChangeDataset: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Condition editor — one condition row
// ---------------------------------------------------------------------------

function ConditionEditor({ condition, devices, onChange, onRemove }) {
  /**
   * Single condition row: type selector + stream picker + operator + value.
   * Operator options are filtered by the selected stream's data_type.
   */

  // Find the selected stream's data_type from the device's streams list.
  const { data: deviceStreams = [] } = useDeviceStreams(condition._device_id);
  const selectedStream = deviceStreams.find((s) => s.id === condition.stream);
  const dataType = selectedStream?.data_type || null;
  const operators = dataType ? OPERATORS_BY_TYPE[dataType] || [] : [];

  const set = (patch) => onChange({ ...condition, ...patch });

  const handleStreamChange = ({ stream, _device_id, _data_type }) => {
    // Reset operator / value when stream changes.
    set({ stream, _device_id, operator: '', threshold_value: '', _data_type });
  };

  return (
    <div className={b.conditionRow}>
      <div className={b.conditionRowInner}>
        {/* Condition type */}
        <select
          className={b.selectSmall}
          value={condition.condition_type}
          onChange={(e) => set({
            condition_type: e.target.value,
            stream: null, _device_id: null,
            operator: '', threshold_value: '', staleness_minutes: '',
            channel: null, _provider_id: null,
            dataset: null, value_key: '', dimension_overrides: null,
          })}
        >
          <option value="stream">Stream value</option>
          <option value="staleness">Not reported in…</option>
          <option value="feed_channel">Feed channel value</option>
          <option value="reference_value">Reference dataset value</option>
        </select>

        {/* Stream picker — for stream and staleness types */}
        {(condition.condition_type === 'stream' || condition.condition_type === 'staleness') && (
          <StreamPicker
            streamId={condition.stream}
            deviceId={condition._device_id}
            onChangeStream={handleStreamChange}
            devices={devices}
          />
        )}

        {/* Feed channel picker */}
        {condition.condition_type === 'feed_channel' && (
          <FeedChannelPicker
            channelId={condition.channel}
            providerId={condition._provider_id}
            onChangeChannel={({ channel, _provider_id }) =>
              set({ channel, _provider_id, operator: '', threshold_value: '' })
            }
          />
        )}

        {/* Reference value picker */}
        {condition.condition_type === 'reference_value' && (
          <ReferenceValuePicker
            datasetId={condition.dataset}
            valueKey={condition.value_key}
            onChangeDataset={({ dataset, value_key }) =>
              set({ dataset, value_key, operator: '', threshold_value: '' })
            }
          />
        )}

        {condition.condition_type === 'stream' && (
          <>
            {/* Operator */}
            <select
              className={b.selectSmall}
              value={condition.operator}
              onChange={(e) => set({ operator: e.target.value, threshold_value: '' })}
              disabled={!dataType}
            >
              <option value="">Operator…</option>
              {operators.map((op) => (
                <option key={op} value={op}>{OPERATOR_LABELS[op] || op}</option>
              ))}
            </select>

            {/* Threshold value — adapts to data type */}
            {dataType === 'boolean' ? (
              <select
                className={b.selectSmall}
                value={condition.threshold_value}
                onChange={(e) => set({ threshold_value: e.target.value })}
                disabled={!condition.operator}
              >
                <option value="">Value…</option>
                <option value="True">true</option>
                <option value="False">false</option>
              </select>
            ) : dataType === 'numeric' ? (
              <input
                type="number"
                className={b.inputSmall}
                placeholder="Value"
                value={condition.threshold_value}
                onChange={(e) => set({ threshold_value: e.target.value })}
                disabled={!condition.operator}
                style={{ width: '100px' }}
              />
            ) : (
              <input
                type="text"
                className={b.inputSmall}
                placeholder="Value"
                value={condition.threshold_value}
                onChange={(e) => set({ threshold_value: e.target.value })}
                disabled={!condition.operator}
                style={{ width: '120px' }}
              />
            )}
          </>
        )}

        {condition.condition_type === 'staleness' && (
          <>
            <input
              type="number"
              min="2"
              className={b.inputSmall}
              placeholder="Minutes"
              value={condition.staleness_minutes}
              onChange={(e) => set({ staleness_minutes: e.target.value })}
              style={{ width: '90px' }}
            />
            <span style={{ fontSize: '0.8125rem', color: '#6B7280' }}>minutes</span>
          </>
        )}

        {/* Numeric operator + threshold for feed_channel and reference_value */}
        {(condition.condition_type === 'feed_channel' || condition.condition_type === 'reference_value') && (
          <>
            <select
              className={b.selectSmall}
              value={condition.operator}
              onChange={(e) => set({ operator: e.target.value })}
              disabled={
                condition.condition_type === 'feed_channel'
                  ? !condition.channel
                  : !condition.value_key
              }
            >
              <option value="">Operator…</option>
              {OPERATORS_BY_TYPE.numeric.map((op) => (
                <option key={op} value={op}>{OPERATOR_LABELS[op] || op}</option>
              ))}
            </select>
            <input
              type="number"
              className={b.inputSmall}
              placeholder="Value"
              value={condition.threshold_value}
              onChange={(e) => set({ threshold_value: e.target.value })}
              disabled={!condition.operator}
              style={{ width: '100px' }}
            />
          </>
        )}
      </div>
      <button type="button" className={b.removeBtn} onClick={onRemove}>Remove</button>
    </div>
  );
}

ConditionEditor.propTypes = {
  condition: PropTypes.object.isRequired,
  devices: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Condition group editor
// ---------------------------------------------------------------------------

function ConditionGroupEditor({ group, devices, groupIndex, onChange, onRemove, showRemove }) {
  /**
   * One condition group: AND/OR toggle + list of conditions.
   */
  const setGroupOp = (op) => onChange({ ...group, logical_operator: op });

  const updateCondition = (ci, patch) => {
    const updated = group.conditions.map((c, i) => (i === ci ? patch : c));
    onChange({ ...group, conditions: updated });
  };

  const addCondition = () => {
    onChange({ ...group, conditions: [...group.conditions, emptyCondition(group.conditions.length)] });
  };

  const removeCondition = (ci) => {
    onChange({ ...group, conditions: group.conditions.filter((_, i) => i !== ci) });
  };

  return (
    <div className={b.conditionGroup}>
      <div className={b.conditionGroupHeader}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span className={b.conditionGroupLabel}>Group {groupIndex + 1}</span>
          <OperatorToggle value={group.logical_operator} onChange={setGroupOp} />
          <span style={{ fontSize: '0.8125rem', color: '#6B7280' }}>between conditions</span>
        </div>
        {showRemove && (
          <button type="button" className={b.removeBtn} onClick={onRemove}>
            Remove group
          </button>
        )}
      </div>

      {group.conditions.map((condition, ci) => (
        <ConditionEditor
          key={ci}
          condition={condition}
          devices={devices}
          onChange={(patch) => updateCondition(ci, patch)}
          onRemove={() => removeCondition(ci)}
        />
      ))}

      <button type="button" className={b.addBtn} onClick={addCondition}>
        + Add condition
      </button>
    </div>
  );
}

ConditionGroupEditor.propTypes = {
  group: PropTypes.object.isRequired,
  devices: PropTypes.array.isRequired,
  groupIndex: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired,
  showRemove: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Notify action editor
// ---------------------------------------------------------------------------

function NotifyActionEditor({ action, groups, users, onChange }) {
  /**
   * Fields for a notification action: channels, groups, users, message template.
   */
  const set = (patch) => onChange({ ...action, ...patch });

  const toggleChannel = (key) => {
    const already = action.notification_channels.includes(key);
    set({
      notification_channels: already
        ? action.notification_channels.filter((c) => c !== key)
        : [...action.notification_channels, key],
    });
  };

  const toggleGroup = (id) => {
    const already = action.group_ids.includes(id);
    set({ group_ids: already ? action.group_ids.filter((x) => x !== id) : [...action.group_ids, id] });
  };

  const toggleUser = (id) => {
    const already = action.user_ids.includes(id);
    set({ user_ids: already ? action.user_ids.filter((x) => x !== id) : [...action.user_ids, id] });
  };

  const insertVar = (v) => {
    set({ message_template: action.message_template + v });
  };

  return (
    <>
      {/* Channels */}
      <div className={b.field}>
        <span className={b.label}>Channels</span>
        <div className={b.channelGrid}>
          {CHANNELS.map(({ key, label }) => (
            <label key={key} className={b.checkboxRow} style={{ margin: 0 }}>
              <input
                type="checkbox"
                checked={action.notification_channels.includes(key)}
                onChange={() => toggleChannel(key)}
              />
              {label}
            </label>
          ))}
        </div>
      </div>

      {/* Groups */}
      {groups.length > 0 && (
        <div className={b.field}>
          <span className={b.label}>Notify groups<span className={b.labelOptional}>optional</span></span>
          <div className={b.multiSelectList}>
            {groups.map((g) => (
              <label key={g.id} className={b.multiSelectItem}>
                <input
                  type="checkbox"
                  checked={action.group_ids.includes(g.id)}
                  onChange={() => toggleGroup(g.id)}
                />
                {g.name}
                {g.is_system && (
                  <span style={{ fontSize: '0.75rem', color: '#9CA3AF', marginLeft: '0.25rem' }}>(system)</span>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Users */}
      {users.length > 0 && (
        <div className={b.field}>
          <span className={b.label}>Notify users<span className={b.labelOptional}>optional</span></span>
          <div className={b.multiSelectList}>
            {users.map((u) => (
              <label key={u.id} className={b.multiSelectItem}>
                <input
                  type="checkbox"
                  checked={action.user_ids.includes(u.id)}
                  onChange={() => toggleUser(u.id)}
                />
                {u.first_name || u.email} {u.last_name || ''}
                <span style={{ fontSize: '0.75rem', color: '#9CA3AF', marginLeft: '0.25rem' }}>
                  ({u.role})
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Message template */}
      <div className={b.field}>
        <span className={b.label}>Message template</span>
        <textarea
          className={b.textarea}
          rows={3}
          value={action.message_template}
          onChange={(e) => set({ message_template: e.target.value })}
          placeholder="e.g. {{device_name}} temperature is {{value}}{{unit}}"
          style={{ maxWidth: '480px' }}
        />
        <div>
          <span className={b.hint}>Insert variable: </span>
          <div className={b.templateHints}>
            {TEMPLATE_VARS.map((v) => (
              <button
                key={v}
                type="button"
                className={b.templateVar}
                onClick={() => insertVar(v)}
                title={`Insert ${v}`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

NotifyActionEditor.propTypes = {
  action: PropTypes.object.isRequired,
  groups: PropTypes.array.isRequired,
  users: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Command action editor
// ---------------------------------------------------------------------------

function CommandActionEditor({ action, devices, deviceTypes, onChange }) {
  /**
   * Fields for a command action: target device, command picker, params form.
   * Commands come from DeviceType.commands JSONB array.
   */
  const set = (patch) => onChange({ ...action, ...patch });

  const selectedDevice = devices.find((d) => d.id === action.target_device) || null;
  const deviceType = selectedDevice
    ? deviceTypes.find((t) => t.id === selectedDevice.device_type)
    : null;
  const commands = deviceType?.commands || [];
  const selectedCommand = commands.find((c) => c.name === action.command?.name) || null;

  const handleDeviceChange = (e) => {
    const did = parseInt(e.target.value, 10) || null;
    set({ target_device: did, command: null });
  };

  const handleCommandChange = (e) => {
    const name = e.target.value;
    if (!name) { set({ command: null }); return; }
    set({ command: { name, params: {} } });
  };

  const handleParamChange = (paramKey, value) => {
    set({ command: { ...action.command, params: { ...(action.command?.params || {}), [paramKey]: value } } });
  };

  return (
    <>
      <div className={b.field}>
        <span className={b.label}>Target device</span>
        <select
          className={b.select}
          value={action.target_device || ''}
          onChange={handleDeviceChange}
          style={{ maxWidth: '320px' }}
        >
          <option value="">Select device…</option>
          {devices.filter((d) => d.status === 'active').map((d) => (
            <option key={d.id} value={d.id}>{d.name} ({d.site_name})</option>
          ))}
        </select>
      </div>

      {commands.length > 0 && (
        <div className={b.field}>
          <span className={b.label}>Command</span>
          <select
            className={b.select}
            value={action.command?.name || ''}
            onChange={handleCommandChange}
            style={{ maxWidth: '320px' }}
          >
            <option value="">Select command…</option>
            {commands.map((c) => (
              <option key={c.name} value={c.name}>{c.label || c.name}</option>
            ))}
          </select>
          {selectedCommand?.description && (
            <p className={b.hint}>{selectedCommand.description}</p>
          )}
        </div>
      )}

      {selectedCommand?.params?.length > 0 && (
        <div className={b.field}>
          <span className={b.label}>Parameters</span>
          {selectedCommand.params.map((param) => (
            <div key={param.key} className={b.field} style={{ marginBottom: '0.5rem' }}>
              <label className={b.label} style={{ fontWeight: 400 }}>
                {param.label || param.key}
                {param.unit && <span className={b.labelOptional}> ({param.unit})</span>}
              </label>
              {param.type === 'bool' ? (
                <select
                  className={b.select}
                  value={action.command?.params?.[param.key] ?? ''}
                  onChange={(e) => handleParamChange(param.key, e.target.value === 'true')}
                  style={{ maxWidth: '160px' }}
                >
                  <option value="">Select…</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  type={param.type === 'int' || param.type === 'float' ? 'number' : 'text'}
                  className={b.input}
                  placeholder={param.default != null ? String(param.default) : ''}
                  min={param.min}
                  max={param.max}
                  defaultValue={param.default != null ? param.default : ''}
                  onChange={(e) => handleParamChange(param.key, e.target.value)}
                  style={{ maxWidth: '200px' }}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {action.target_device && commands.length === 0 && (
        <p className={b.hint}>This device type has no commands defined.</p>
      )}
    </>
  );
}

CommandActionEditor.propTypes = {
  action: PropTypes.object.isRequired,
  devices: PropTypes.array.isRequired,
  deviceTypes: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
};

// ---------------------------------------------------------------------------
// Action editor
// ---------------------------------------------------------------------------

function ActionEditor({ action, actionIndex, groups, users, devices, deviceTypes, onChange, onRemove, showRemove }) {
  /**
   * Single action card with type selector and type-specific fields.
   */
  const set = (patch) => onChange({ ...action, ...patch });

  return (
    <div className={b.actionCard}>
      <div className={b.actionCardHeader}>
        <span className={b.actionCardTitle}>Action {actionIndex + 1}</span>
        {showRemove && (
          <button type="button" className={b.removeBtn} onClick={onRemove}>Remove</button>
        )}
      </div>

      <div className={b.field}>
        <span className={b.label}>Type</span>
        <select
          className={b.select}
          value={action.action_type}
          onChange={(e) => set({
            action_type: e.target.value,
            notification_channels: ['in_app', 'email'],
            group_ids: [], user_ids: [], message_template: '',
            target_device: null, command: null,
          })}
          style={{ maxWidth: '200px' }}
        >
          <option value="notify">Send notification</option>
          <option value="command">Send device command</option>
        </select>
      </div>

      {action.action_type === 'notify' && (
        <NotifyActionEditor action={action} groups={groups} users={users} onChange={onChange} />
      )}
      {action.action_type === 'command' && (
        <CommandActionEditor
          action={action}
          devices={devices}
          deviceTypes={deviceTypes}
          onChange={onChange}
        />
      )}
    </div>
  );
}

ActionEditor.propTypes = {
  action: PropTypes.object.isRequired,
  actionIndex: PropTypes.number.isRequired,
  groups: PropTypes.array.isRequired,
  users: PropTypes.array.isRequired,
  devices: PropTypes.array.isRequired,
  deviceTypes: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired,
  showRemove: PropTypes.bool.isRequired,
};

// ---------------------------------------------------------------------------
// Review step
// ---------------------------------------------------------------------------

function ReviewStep({ form, devices, groups, users }) {
  /**
   * Read-only summary of all form state before saving.
   */
  const dayNames = (form.active_days || []).map((d) => DAY_LABELS[d]).join(', ');
  const deviceById = Object.fromEntries(devices.map((d) => [d.id, d]));
  const groupById = Object.fromEntries(groups.map((g) => [g.id, g]));
  const userById = Object.fromEntries(users.map((u) => [u.id, u]));

  return (
    <div>
      {/* Name & settings */}
      <div className={b.reviewSection}>
        <p className={b.reviewSectionTitle}>Name & Settings</p>
        <div className={b.reviewRow}><span className={b.reviewLabel}>Name</span><span className={b.reviewValue}>{form.name}</span></div>
        {form.description && <div className={b.reviewRow}><span className={b.reviewLabel}>Description</span><span className={b.reviewValue}>{form.description}</span></div>}
        <div className={b.reviewRow}><span className={b.reviewLabel}>Status</span><span className={b.reviewValue}>{form.is_active ? 'Active' : 'Inactive'}</span></div>
        {form.cooldown_minutes && <div className={b.reviewRow}><span className={b.reviewLabel}>Cooldown</span><span className={b.reviewValue}>{form.cooldown_minutes} minutes</span></div>}
      </div>

      {/* Schedule gate */}
      {form.active_days.length > 0 && (
        <div className={b.reviewSection}>
          <p className={b.reviewSectionTitle}>Schedule Gate</p>
          <div className={b.reviewRow}><span className={b.reviewLabel}>Active days</span><span className={b.reviewValue}>{dayNames}</span></div>
          {form.active_from && (
            <div className={b.reviewRow}>
              <span className={b.reviewLabel}>Time window</span>
              <span className={b.reviewValue}>{form.active_from} – {form.active_to}</span>
            </div>
          )}
        </div>
      )}

      {/* Conditions */}
      <div className={b.reviewSection}>
        <p className={b.reviewSectionTitle}>
          Conditions — groups combined with {form.condition_group_operator}
        </p>
        {form.condition_groups.map((g, gi) => (
          <div key={gi} className={b.reviewGroup}>
            <p style={{ fontSize: '0.8125rem', fontWeight: 600, margin: '0 0 0.5rem', color: '#374151' }}>
              Group {gi + 1} — {g.logical_operator} between conditions
            </p>
            {g.conditions.map((c, ci) => (
              <div key={ci} className={b.reviewCondition}>
                {c.condition_type === 'stream'
                  ? `Stream #${c.stream} ${c.operator} ${c.threshold_value}`
                  : `Stream #${c.stream} not reported in ${c.staleness_minutes} minutes`}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className={b.reviewSection}>
        <p className={b.reviewSectionTitle}>Actions</p>
        {form.actions.map((a, ai) => (
          <div key={ai} className={b.reviewGroup}>
            <p style={{ fontSize: '0.8125rem', fontWeight: 600, margin: '0 0 0.5rem', color: '#374151' }}>
              Action {ai + 1} — {a.action_type === 'notify' ? 'Notification' : 'Device command'}
            </p>
            {a.action_type === 'notify' && (
              <>
                <div className={b.reviewCondition}>Channels: {a.notification_channels.join(', ') || '—'}</div>
                {a.group_ids.length > 0 && (
                  <div className={b.reviewCondition}>
                    Groups: {a.group_ids.map((id) => groupById[id]?.name || `#${id}`).join(', ')}
                  </div>
                )}
                {a.user_ids.length > 0 && (
                  <div className={b.reviewCondition}>
                    Users: {a.user_ids.map((id) => userById[id]?.email || `#${id}`).join(', ')}
                  </div>
                )}
                <div className={b.reviewCondition}>Message: {a.message_template}</div>
              </>
            )}
            {a.action_type === 'command' && (
              <>
                <div className={b.reviewCondition}>
                  Device: {deviceById[a.target_device]?.name || `#${a.target_device}`}
                </div>
                <div className={b.reviewCondition}>Command: {a.command?.name}</div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

ReviewStep.propTypes = {
  form: PropTypes.object.isRequired,
  devices: PropTypes.array.isRequired,
  groups: PropTypes.array.isRequired,
  users: PropTypes.array.isRequired,
};

// ---------------------------------------------------------------------------
// Main builder component
// ---------------------------------------------------------------------------

function RuleBuilder() {
  /**
   * Multi-step rule builder for create (/app/rules/new) and edit (/app/rules/:id/edit).
   * Loads existing rule when in edit mode; saves via POST (create) or PUT (update).
   * Ref: SPEC.md § Feature: Rules Engine, § UI/UX Notes — Rule Builder
   */
  const { id: ruleId } = useParams();
  const isEdit = !!ruleId;
  const navigate = useNavigate();

  // Step state
  const [step, setStep] = useState(1);
  const [stepError, setStepError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);

  // Form state
  const [form, setForm] = useState(defaultForm());
  const [initialised, setInitialised] = useState(!isEdit);

  // Data dependencies
  const { data: existingRule, isLoading: ruleLoading } = useRule(ruleId);
  const { data: devices = [] } = useDevices();
  const { data: deviceTypes = [] } = useDeviceTypes();
  const { data: groups = [] } = useGroups();
  const { data: users = [] } = useUsers();

  const createRule = useCreateRule();
  const updateRule = useUpdateRule();

  // Populate form when editing an existing rule.
  useEffect(() => {
    if (isEdit && existingRule && !initialised) {
      setForm(formFromRule(existingRule));
      setInitialised(true);
    }
  }, [isEdit, existingRule, initialised]);

  // ---------------------------------------------------------------------------
  // Navigation helpers
  // ---------------------------------------------------------------------------

  const handleNext = () => {
    const err = validateStep(step, form);
    if (err) { setStepError(err); return; }
    setStepError('');
    setStep((s) => s + 1);
  };

  const handleBack = () => {
    setStepError('');
    setStep((s) => s - 1);
  };

  const handleSave = async () => {
    setSaveError('');
    setSaving(true);
    try {
      const payload = buildPayload(form);
      if (isEdit) {
        await updateRule.mutateAsync({ ruleId, data: payload });
        navigate(`/app/rules/${ruleId}`);
      } else {
        const created = await createRule.mutateAsync(payload);
        navigate(`/app/rules/${created.id}`);
      }
    } catch (e) {
      const detail = e?.response?.data;
      setSaveError(
        typeof detail === 'string'
          ? detail
          : JSON.stringify(detail) || 'Failed to save rule. Check the form and try again.'
      );
    } finally {
      setSaving(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Form updaters
  // ---------------------------------------------------------------------------

  const updateGroup = (gi, patch) => {
    setForm((f) => {
      const groups = f.condition_groups.map((g, i) => (i === gi ? patch : g));
      return { ...f, condition_groups: groups };
    });
  };

  const addGroup = () => {
    setForm((f) => ({
      ...f,
      condition_groups: [...f.condition_groups, emptyGroup(f.condition_groups.length)],
    }));
  };

  const removeGroup = (gi) => {
    setForm((f) => ({
      ...f,
      condition_groups: f.condition_groups.filter((_, i) => i !== gi),
    }));
  };

  const updateAction = (ai, patch) => {
    setForm((f) => {
      const actions = f.actions.map((a, i) => (i === ai ? patch : a));
      return { ...f, actions };
    });
  };

  const addAction = () => {
    setForm((f) => ({ ...f, actions: [...f.actions, emptyAction()] }));
  };

  const removeAction = (ai) => {
    setForm((f) => ({ ...f, actions: f.actions.filter((_, i) => i !== ai) }));
  };

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (isEdit && ruleLoading) return <p className={styles.loading}>Loading rule…</p>;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const backLabel = isEdit ? `← Rule` : '← Rules';
  const backTo = isEdit ? `/app/rules/${ruleId}` : '/app/rules';

  return (
    <div>
      <div className={styles.pageHeader}>
        <Link to={backTo} className={styles.link}>{backLabel}</Link>
        <h1 className={styles.pageTitle} style={{ margin: '0 0 0 1rem' }}>
          {isEdit ? 'Edit rule' : 'New rule'}
        </h1>
      </div>

      <StepBar current={step} />

      <div className={b.stepBody}>
        <h2 className={b.stepTitle}>{STEPS[step - 1]}</h2>

        {/* ---- Step 1: Name & Settings ---- */}
        {step === 1 && (
          <>
            <div className={b.field}>
              <label className={b.label}>Rule name</label>
              <input
                className={b.input}
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. High temperature alert"
                autoFocus
              />
            </div>
            <div className={b.field}>
              <label className={b.label}>
                Description<span className={b.labelOptional}>optional</span>
              </label>
              <textarea
                className={b.textarea}
                rows={2}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="What does this rule do?"
              />
            </div>
            <div className={b.checkboxRow}>
              <input
                type="checkbox"
                id="is_active"
                checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
              />
              <label htmlFor="is_active">Enable rule immediately after saving</label>
            </div>
            <div className={b.field} style={{ marginTop: '1rem' }}>
              <label className={b.label}>
                Cooldown<span className={b.labelOptional}>optional</span>
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  className={b.input}
                  type="number"
                  min="1"
                  value={form.cooldown_minutes}
                  onChange={(e) => setForm((f) => ({ ...f, cooldown_minutes: e.target.value }))}
                  placeholder="e.g. 30"
                  style={{ maxWidth: '120px' }}
                />
                <span style={{ fontSize: '0.875rem', color: '#6B7280' }}>minutes between firings</span>
              </div>
              <p className={b.hint}>Minimum time before this rule can fire again after the condition clears.</p>
            </div>
          </>
        )}

        {/* ---- Step 2: Schedule Gate ---- */}
        {step === 2 && (
          <>
            <p className={b.hint} style={{ marginBottom: '1rem' }}>
              Limit when this rule evaluates. Leave blank to evaluate at all times.
            </p>
            <div className={b.field}>
              <span className={b.label}>Active days</span>
              <div className={b.shortcutRow}>
                {[
                  { label: 'Weekdays', days: WEEKDAYS },
                  { label: 'Weekends', days: WEEKEND },
                  { label: 'Every day', days: ALL_DAYS },
                  { label: 'Clear', days: [] },
                ].map(({ label, days }) => (
                  <button
                    key={label}
                    type="button"
                    className={b.shortcutBtn}
                    onClick={() => setForm((f) => ({ ...f, active_days: days }))}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className={b.dayGrid}>
                {DAY_LABELS.map((name, i) => {
                  const active = form.active_days.includes(i);
                  return (
                    <button
                      key={i}
                      type="button"
                      className={`${b.dayChip} ${active ? b.dayChipActive : ''}`}
                      onClick={() => {
                        setForm((f) => ({
                          ...f,
                          active_days: active
                            ? f.active_days.filter((d) => d !== i)
                            : [...f.active_days, i].sort((a, c) => a - c),
                        }));
                      }}
                    >
                      {name}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className={b.field}>
              <span className={b.label}>
                Time window<span className={b.labelOptional}>optional — set both or neither</span>
              </span>
              <div className={b.timeRow}>
                <label style={{ fontSize: '0.875rem', color: '#374151' }}>From</label>
                <input
                  type="time"
                  className={b.input}
                  value={form.active_from}
                  onChange={(e) => setForm((f) => ({ ...f, active_from: e.target.value }))}
                  style={{ maxWidth: '140px' }}
                />
                <label style={{ fontSize: '0.875rem', color: '#374151' }}>To</label>
                <input
                  type="time"
                  className={b.input}
                  value={form.active_to}
                  onChange={(e) => setForm((f) => ({ ...f, active_to: e.target.value }))}
                  style={{ maxWidth: '140px' }}
                />
              </div>
              <p className={b.hint}>Times are evaluated in your tenant&apos;s configured timezone.</p>
            </div>
          </>
        )}

        {/* ---- Step 3: Conditions ---- */}
        {step === 3 && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <span className={b.label} style={{ marginBottom: 0 }}>Combine groups with</span>
              <OperatorToggle
                value={form.condition_group_operator}
                onChange={(op) => setForm((f) => ({ ...f, condition_group_operator: op }))}
              />
            </div>
            {form.condition_groups.map((group, gi) => (
              <ConditionGroupEditor
                key={gi}
                group={group}
                groupIndex={gi}
                devices={devices}
                onChange={(patch) => updateGroup(gi, patch)}
                onRemove={() => removeGroup(gi)}
                showRemove={form.condition_groups.length > 1}
              />
            ))}
            <button type="button" className={b.addBtn} onClick={addGroup}>
              + Add condition group
            </button>
          </>
        )}

        {/* ---- Step 4: Actions ---- */}
        {step === 4 && (
          <>
            {form.actions.map((action, ai) => (
              <ActionEditor
                key={ai}
                action={action}
                actionIndex={ai}
                groups={groups}
                users={users}
                devices={devices}
                deviceTypes={deviceTypes}
                onChange={(patch) => updateAction(ai, patch)}
                onRemove={() => removeAction(ai)}
                showRemove={form.actions.length > 1}
              />
            ))}
            <button type="button" className={b.addBtn} onClick={addAction}>
              + Add action
            </button>
          </>
        )}

        {/* ---- Step 5: Review ---- */}
        {step === 5 && (
          <ReviewStep
            form={form}
            devices={devices}
            groups={groups}
            users={users}
          />
        )}
      </div>

      {/* Step error */}
      {stepError && (
        <p className={styles.error} style={{ marginBottom: '1rem' }}>{stepError}</p>
      )}
      {saveError && (
        <p className={styles.error} style={{ marginBottom: '1rem' }}>{saveError}</p>
      )}

      {/* Navigation row */}
      <div className={b.navRow}>
        <div>
          {step > 1 && (
            <button type="button" className={styles.secondaryButton} onClick={handleBack}>
              ← Back
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <Link to={backTo} className={styles.secondaryButton}>Cancel</Link>
          {step < STEPS.length ? (
            <button type="button" className={styles.primaryButton} onClick={handleNext}>
              Next →
            </button>
          ) : (
            <button
              type="button"
              className={styles.primaryButton}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create rule'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default RuleBuilder;
