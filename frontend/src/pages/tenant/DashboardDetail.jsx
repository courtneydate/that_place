/**
 * DashboardDetail — canvas page for a single dashboard.
 *
 * Renders widgets in a fixed grid (1/2/3 columns) ordered by position.order.
 * Only value_card widgets are rendered in Sprint 11; other types show a placeholder.
 * Auto-refreshes widget data every 30 seconds via React Query refetchInterval.
 */
import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  useDashboard,
  useUpdateDashboard,
  useCreateWidget,
  useDeleteWidget,
} from '../../hooks/useDashboards';
import ValueCard from '../../components/ValueCard';
import WidgetBuilderModal from '../../components/WidgetBuilderModal';
import styles from './DashboardDetail.module.css';
import pageStyles from '../admin/AdminPage.module.css';

const REFETCH_INTERVAL = 30000;
const COLUMN_OPTIONS = [1, 2, 3];

/** Sort widgets by position.order ascending (falling back to created_at order). */
function sortWidgets(widgets) {
  return [...widgets].sort((a, b) => {
    const oa = a.position?.order ?? Infinity;
    const ob = b.position?.order ?? Infinity;
    return oa - ob;
  });
}

function WidgetPlaceholder({ widgetType }) {
  return (
    <div className={styles.placeholderCard}>
      <span className={styles.placeholderLabel}>{widgetType.replace(/_/g, ' ')}</span>
      <span className={styles.placeholderNote}>Available in a future sprint</span>
    </div>
  );
}

function DashboardDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const canEdit = user?.tenant_role === 'admin' || user?.tenant_role === 'operator';

  const { data: dashboard, isLoading, error } = useDashboard(Number(id));
  const updateDashboard = useUpdateDashboard(Number(id));
  const createWidget = useCreateWidget(Number(id));
  const deleteWidget = useDeleteWidget(Number(id));

  const [showBuilder, setShowBuilder] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameInput, setNameInput] = useState('');
  const [columnsInput, setColumnsInput] = useState(2);

  const handleEditStart = () => {
    setNameInput(dashboard.name);
    setColumnsInput(dashboard.columns);
    setEditingName(true);
  };

  const handleEditSave = async () => {
    try {
      await updateDashboard.mutateAsync({ name: nameInput.trim(), columns: columnsInput });
      setEditingName(false);
    } catch {
      // leave modal open on error — user can retry
    }
  };

  const handleAddWidget = async (payload) => {
    try {
      await createWidget.mutateAsync(payload);
      setShowBuilder(false);
    } catch {
      // leave modal open on error
    }
  };

  const handleRemoveWidget = async (widgetId) => {
    if (!window.confirm('Remove this widget?')) return;
    await deleteWidget.mutateAsync(widgetId);
  };

  if (isLoading) return <p className={pageStyles.loading}>Loading dashboard…</p>;
  if (error) return <p className={pageStyles.error}>Dashboard not found.</p>;

  const widgets = sortWidgets(dashboard.widgets || []);
  const nextOrder = widgets.length;

  return (
    <div>
      {/* Header */}
      <div className={pageStyles.pageHeader}>
        <Link to="/app/dashboards" className={pageStyles.link}>← Dashboards</Link>
        {editingName ? (
          <div className={styles.inlineEdit}>
            <input
              className={pageStyles.input}
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              autoFocus
            />
            <select
              className={pageStyles.input}
              value={columnsInput}
              onChange={(e) => setColumnsInput(Number(e.target.value))}
            >
              {COLUMN_OPTIONS.map((n) => (
                <option key={n} value={n}>{n} col{n !== 1 ? 's' : ''}</option>
              ))}
            </select>
            <button className={pageStyles.primaryButton} onClick={handleEditSave}>Save</button>
            <button className={pageStyles.secondaryButton} onClick={() => setEditingName(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <>
            <h1 className={pageStyles.pageTitle}>{dashboard.name}</h1>
            {canEdit && (
              <div className={styles.headerActions}>
                <button className={pageStyles.secondaryButton} onClick={handleEditStart}>
                  Edit
                </button>
                <button
                  className={pageStyles.primaryButton}
                  onClick={() => setShowBuilder(true)}
                >
                  + Add Widget
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Canvas */}
      {widgets.length === 0 ? (
        <p className={pageStyles.empty}>
          No widgets yet.{canEdit ? ' Click "+ Add Widget" to add one.' : ''}
        </p>
      ) : (
        <div
          className={styles.grid}
          style={{ '--columns': dashboard.columns }}
        >
          {widgets.map((widget) => {
            if (widget.widget_type === 'value_card') {
              return (
                <ValueCard
                  key={widget.id}
                  streamId={widget.stream_ids?.[0]}
                  config={widget.config}
                  refetchInterval={REFETCH_INTERVAL}
                  canEdit={canEdit}
                  onRemove={() => handleRemoveWidget(widget.id)}
                />
              );
            }
            return <WidgetPlaceholder key={widget.id} widgetType={widget.widget_type} />;
          })}
        </div>
      )}

      {/* Widget builder modal */}
      {showBuilder && (
        <WidgetBuilderModal
          dashboardId={Number(id)}
          nextOrder={nextOrder}
          onSubmit={handleAddWidget}
          onClose={() => setShowBuilder(false)}
        />
      )}
    </div>
  );
}

export default DashboardDetail;
