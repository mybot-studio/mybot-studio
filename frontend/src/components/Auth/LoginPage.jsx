import React, { useState } from 'react';
import { Bot, Lock, User, ArrowRight, Loader2, Sparkles, KeyRound } from 'lucide-react';
import { useI18n } from '../../locales/i18n';
import { api } from '../../services/api';
import MatrixCanvas from '../Visuals/MatrixCanvas';

export default function LoginPage({ onLoginSuccess }) {
  const { t, dir } = useI18n();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin1234');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;

    setLoading(true);
    setError('');
    try {
      const res = await api.login(username.trim(), password.trim());
      localStorage.setItem('mybot_token', res.access_token);
      setLoading(false);
      onLoginSuccess(res);
    } catch (err) {
      setLoading(false);
      setError(err.message || t('login.error'));
    }
  };

  return (
    <div className="w-screen h-screen bg-[#0a0f18] flex items-center justify-center p-6 relative overflow-hidden">
      {/* Dynamic Animated Matrix/Neural Particle Canvas */}
      <MatrixCanvas />

      {/* Futuristic Blur Backdrop */}
      <div className="absolute inset-0 bg-radial from-emerald-500/10 via-transparent to-black/80 pointer-events-none" />

      <div className="w-full max-w-md bg-surface/85 border border-emerald-500/30 rounded-3xl shadow-2xl p-8 backdrop-blur-2xl space-y-6 relative z-10 animate-in fade-in zoom-in-95 ring-1 ring-emerald-500/20">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="w-14 h-14 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 flex items-center justify-center mx-auto shadow-lg shadow-emerald-500/10">
            <Bot size={30} />
          </div>
          <h1 className="text-xl font-extrabold text-foreground tracking-tight">
            {t('login.title')}
          </h1>
          <p className="text-xs text-muted">
            {t('login.subtitle')}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <User size={13} className="text-emerald-400" />
              <span>{t('login.username_label')}</span>
            </label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              className="w-full bg-surface-secondary/90 border border-border rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder:text-field-placeholder outline-none focus:border-emerald-500 transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <Lock size={13} className="text-emerald-400" />
              <span>{t('login.password_label')}</span>
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-surface-secondary/90 border border-border rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder:text-field-placeholder outline-none focus:border-emerald-500 font-mono transition-colors"
            />
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-danger/10 border border-danger/20 text-danger text-xs text-center font-medium leading-relaxed">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-emerald-500 text-black text-xs font-bold shadow-lg shadow-emerald-500/20 hover:bg-emerald-400 disabled:opacity-50 transition-all"
          >
            {loading ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                <span>{t('login.logging_in')}</span>
              </>
            ) : (
              <>
                <span>{t('login.login_btn')}</span>
                <ArrowRight size={14} className={dir === 'rtl' ? 'rotate-180' : ''} />
              </>
            )}
          </button>
        </form>

        {/* Hint banner */}
        <div className="p-3 rounded-xl bg-surface-secondary/60 border border-border/70 text-[11px] text-muted text-center flex items-center justify-center gap-1.5">
          <KeyRound size={13} className="text-emerald-400" />
          <span>{t('login.default_hint')}</span>
        </div>
      </div>
    </div>
  );
}
