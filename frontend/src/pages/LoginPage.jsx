import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { AuthCard, ErrorText, Field, SubmitButton } from '../components/AuthForm'
import { errorKey } from '../services/api'
import { useAuth } from '../services/auth.jsx'

export default function LoginPage() {
  const { t } = useTranslation()
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(t(errorKey(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title={t('auth.loginTitle')}>
      <form onSubmit={onSubmit}>
        <Field label={t('auth.email')} type="email" required autoComplete="email"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label={t('auth.password')} type="password" required autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <ErrorText>{error}</ErrorText>
        <SubmitButton busy={busy} busyText={t('auth.loading')}>{t('auth.submitLogin')}</SubmitButton>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        {t('auth.noAccount')}{' '}
        <Link to="/register" className="font-medium text-slate-900 underline">{t('nav.register')}</Link>
      </p>
    </AuthCard>
  )
}
