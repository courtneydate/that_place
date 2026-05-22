import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminNotificationBell from './AdminNotificationBell';

// Mutable state the mocked hooks read at render time.
let mockUnread = 0;
let mockNotifications = [];
const mockMarkAllRead = jest.fn();
const mockMarkRead = jest.fn(() => Promise.resolve());

jest.mock('../hooks/useNotifications', () => ({
  useUnreadCount: () => ({ data: mockUnread }),
  useNotifications: () => ({ data: mockNotifications }),
  useMarkRead: () => ({ mutateAsync: mockMarkRead }),
  useMarkAllRead: () => ({ mutate: mockMarkAllRead, isPending: false }),
}));

function renderBell() {
  return render(
    <MemoryRouter>
      <AdminNotificationBell />
    </MemoryRouter>,
  );
}

describe('AdminNotificationBell', () => {
  beforeEach(() => {
    mockUnread = 0;
    mockNotifications = [];
    jest.clearAllMocks();
  });

  it('shows the unread badge when there are unread notifications', () => {
    mockUnread = 3;
    renderBell();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows no badge when there are no unread notifications', () => {
    mockUnread = 0;
    renderBell();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('lists notification messages when the panel is opened', () => {
    mockUnread = 1;
    mockNotifications = [
      {
        id: 1,
        event_type: 'tenant_created',
        message: 'New tenant created: Acme.',
        sent_at: new Date().toISOString(),
        is_read: false,
      },
    ];
    renderBell();
    fireEvent.click(screen.getByLabelText(/Notifications/));
    expect(screen.getByText('New tenant created: Acme.')).toBeInTheDocument();
  });

  it('shows the empty state when there are no notifications', () => {
    renderBell();
    fireEvent.click(screen.getByLabelText(/Notifications/));
    expect(screen.getByText('No notifications yet.')).toBeInTheDocument();
  });

  it('triggers mark-all-read', () => {
    mockUnread = 2;
    mockNotifications = [
      {
        id: 1,
        event_type: 'tenant_created',
        message: 'msg',
        sent_at: new Date().toISOString(),
        is_read: false,
      },
    ];
    renderBell();
    fireEvent.click(screen.getByLabelText(/Notifications/));
    fireEvent.click(screen.getByText('Mark all as read'));
    expect(mockMarkAllRead).toHaveBeenCalled();
  });
});
