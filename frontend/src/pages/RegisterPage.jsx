import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { AuthCard, ErrorText, Field, SubmitButton } from '../components/AuthForm'
import api, { errorKey } from '../services/api'
import { useAuth } from '../services/auth.jsx'

const ROLES = [
  { value: 'buyer', hint: 'auth.roleBuyerHint' },
  { value: 'seller', hint: 'auth.roleSellerHint' },
]

export default function RegisterPage() {
  const { t } = useTranslation()
  const { register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [role, setRole] = useState('buyer')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [invite, setInvite] = useState('')
  // On the public demo sellers register only with an invite code
  const [inviteRequired, setInviteRequired] = useState(false)

  useEffect(() => {
    api.get('/auth/options').then((res) => setInviteRequired(res.data.seller_invite_required)).catch(() => {})
  }, [])

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    // Same limits as the backend (bcrypt allows max 72 bytes)
    if (password.length < 8 || password.length > 72) return setError(t('errors.passwordLength'))
    if (password !== confirm) return setError(t('errors.passwordMismatch'))
    setBusy(true)
    try {
      await register(email, password, role, invite)
      navigate('/')
    } catch (err) {
      setError(t(errorKey(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title={t('auth.registerTitle')}>
      <form onSubmit={onSubmit}>
        <Field label={t('auth.email')} type="email" required autoComplete="email"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label={t('auth.password')} type="password" required autoComplete="new-password"
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <Field label={t('auth.passwordConfirm')} type="password" required autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />

        <span className="mb-1 block text-sm text-slate-600">{t('auth.role')}</span>
        <div className="mb-6 grid grid-cols-2 gap-2">
          {ROLES.map((r) => (
            <button
              key={r.value}
              type="button"
              onClick={() => setRole(r.value)}
              className={`rounded-md border px-3 py-2 text-left ${
                role === r.value ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 hover:border-slate-500'
              }`}
            >
              <span className="block font-medium">{t(`roles.${r.value}`)}</span>
              <span className={`block text-xs ${role === r.value ? 'text-slate-300' : 'text-slate-500'}`}>
                {t(r.hint)}
              </span>
            </button>
          ))}
        </div>

        {role === 'seller' && inviteRequired && (
          <>
            <Field label={t('auth.inviteCode')} required autoComplete="off"
              value={invite} onChange={(e) => setInvite(e.target.value)} />
            <p className="-mt-2 mb-4 text-xs text-slate-500">{t('auth.inviteHint')}</p>
          </>
        )}

        <ErrorText>{error}</ErrorText>
        <SubmitButton busy={busy} busyText={t('auth.loading')}>{t('auth.submitRegister')}</SubmitButton>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        {t('auth.haveAccount')}{' '}
        <Link to="/login" className="font-medium text-slate-900 underline">{t('nav.login')}</Link>
      </p>
    </AuthCard>
  )
}
