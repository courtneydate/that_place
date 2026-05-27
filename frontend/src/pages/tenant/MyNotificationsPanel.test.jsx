/**
 * Sprint 26 — MyNotificationsPanel tests.
 *
 * The panel is a small per-rule, per-user channel toggle. These tests cover:
 *   - renders 4 toggles pre-loaded from the prefs query
 *   - hides itself when the prefs endpoint returns 403 (user not a target)
 *   - toggling a channel calls the save mutation with the inverted prefs
 *   - displays a save error when the mutation rejects
 *   - renders nothing while the prefs are still loading
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MyNotificationsPanel from './MyNotificationsPanel';

let mockPrefsQuery = { isLoading: true, isError: false, data: null, error: null };
const mockSaveMutate = jest.fn(() => Promise.resolve());
let mockSaveState = { isPending: false };

jest.mock('../../hooks/useRules', () => ({
  useMyRuleNotificationPrefs: () => mockPrefsQuery,
  useSaveMyRuleNotificationPrefs: () => ({
    mutateAsync: mockSaveMutate,
    isPending: mockSaveState.isPending,
  }),
}));

beforeEach(() => {
  mockPrefsQuery = { isLoading: true, isError: false, data: null, error: null };
  mockSaveState = { isPending: false };
  mockSaveMutate.mockReset();
  mockSaveMutate.mockResolvedValue({});
});

function setPrefs(prefs) {
  mockPrefsQuery = { isLoading: false, isError: false, data: prefs, error: null };
}

describe('MyNotificationsPanel', () => {
  it('renders nothing while prefs are loading', () => {
    const { container } = render(<MyNotificationsPanel ruleId={1} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders 4 toggles preloaded from the prefs query', () => {
    setPrefs({ in_app: true, email: false, sms: true, push: true });
    render(<MyNotificationsPanel ruleId={1} />);

    expect(screen.getByRole('heading', { name: /my notifications/i })).toBeInTheDocument();
    expect(screen.getByLabelText('In-app')).toBeChecked();
    expect(screen.getByLabelText('Email')).not.toBeChecked();
    expect(screen.getByLabelText('SMS')).toBeChecked();
    expect(screen.getByLabelText('Push')).toBeChecked();
  });

  it('toggling a channel calls the save mutation with inverted prefs', async () => {
    setPrefs({ in_app: true, email: true, sms: true, push: true });
    render(<MyNotificationsPanel ruleId={1} />);

    fireEvent.click(screen.getByLabelText('Email'));

    await waitFor(() => expect(mockSaveMutate).toHaveBeenCalledTimes(1));
    expect(mockSaveMutate).toHaveBeenCalledWith({
      in_app: true, email: false, sms: true, push: true,
    });
  });

  it('hides the panel when the prefs endpoint returns 403 (not targeted)', () => {
    mockPrefsQuery = {
      isLoading: false,
      isError: true,
      data: null,
      error: { response: { status: 403 } },
    };
    const { container } = render(<MyNotificationsPanel ruleId={1} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the save error when the mutation rejects', async () => {
    setPrefs({ in_app: true, email: true, sms: true, push: true });
    mockSaveMutate.mockRejectedValueOnce({
      response: { data: { error: { message: 'Save failed.' } } },
    });
    render(<MyNotificationsPanel ruleId={1} />);

    fireEvent.click(screen.getByLabelText('Push'));

    await waitFor(() =>
      expect(screen.getByText('Save failed.')).toBeInTheDocument(),
    );
  });

  it('renders an error message for non-403 errors', () => {
    mockPrefsQuery = {
      isLoading: false,
      isError: true,
      data: null,
      error: { response: { status: 500 } },
    };
    render(<MyNotificationsPanel ruleId={1} />);
    expect(
      screen.getByText(/failed to load notification preferences/i),
    ).toBeInTheDocument();
  });
});
