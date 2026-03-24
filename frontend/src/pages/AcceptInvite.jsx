/**
 * AcceptInvite — set password and activate account from an invite link.
 *
 * Public page (no auth required). The token comes from the URL path param.
 * On success, stores JWT tokens and navigates to the app home.
 */
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import styles from './Login.module.css';

function AcceptInvite() {
  const { token } = useParams();
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();

  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const validate = () => {
    if (!firstName.trim()) return 'First name is required.';
    if (!lastName.trim()) return 'Last name is required.';
    if (password.length < 8) return 'Password must be at least 8 characters.';
    if (password !== confirmPassword) return 'Passwords do not match.';
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const validationError = validate();
    if (validationError) { setError(validationError); return; }

    setIsLoading(true);
    try {
      await acceptInvite(token, firstName, lastName, password);
      navigate('/', { replace: true });
    } catch (err) {
      const errorData = err.response?.data?.error;
      const message =
        errorData?.details?.token?.[0] ||
        errorData?.details?.non_field_errors?.[0] ||
        errorData?.message ||
        'Failed to accept invite. The link may have expired or already been used.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <h1 className={styles.title}>That Place</h1>
        <p className={styles.subtitle}>Set your password to activate your account</p>

        <form onSubmit={handleSubmit} noValidate className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="firstName" className={styles.label}>First name</label>
            <input
              id="firstName"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className={styles.input}
              autoComplete="given-name"
              disabled={isLoading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="lastName" className={styles.label}>Last name</label>
            <input
              id="lastName"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className={styles.input}
              autoComplete="family-name"
              disabled={isLoading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="password" className={styles.label}>Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={styles.input}
              autoComplete="new-password"
              disabled={isLoading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="confirmPassword" className={styles.label}>Confirm password</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className={styles.input}
              autoComplete="new-password"
              disabled={isLoading}
            />
          </div>

          {error && <p className={styles.error} role="alert">{error}</p>}

          <button type="submit" className={styles.button} disabled={isLoading}>
            {isLoading ? 'Activating…' : 'Activate account'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default AcceptInvite;
