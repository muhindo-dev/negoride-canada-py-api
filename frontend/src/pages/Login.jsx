import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { FiArrowRight, FiEye, FiEyeOff, FiLock, FiLogIn, FiMail, FiShield } from 'react-icons/fi';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.response?.data?.message || err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <div className="login-kicker">
            <FiShield />
            <span>Secure admin access</span>
          </div>
          <div className="login-logo">
            <span className="logo-mark">NR</span>
            <h1>NegoRide Canada</h1>
          </div>
          <p className="login-subtitle">Admin Dashboard</p>
          <p className="login-description">
            Review users, bookings, negotiations, payouts, and platform activity from one control room.
          </p>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <div className="input-wrapper">
              <span className="input-icon-slot">
                <FiMail className="input-icon" />
              </span>
              <input
                id="email"
                type="email"
                placeholder="admin@negoride.ca"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <div className="input-wrapper input-wrapper--with-action">
              <span className="input-icon-slot">
                <FiLock className="input-icon" />
              </span>
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="input-action"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <FiEyeOff /> : <FiEye />}
              </button>
            </div>
          </div>

          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={loading}>
            {loading ? <span className="spinner" /> : <FiLogIn />}
            {loading ? 'Signing in…' : 'Sign In'}
          </button>

          <div className="login-helper">
            <span>Super admin</span>
            <span className="login-helper-divider" />
            <span>Protected session</span>
            <FiArrowRight />
          </div>
        </form>
      </div>
    </div>
  );
}
