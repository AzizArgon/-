import { useTranslation } from 'react-i18next'
import { useAuth } from '../services/auth.jsx'

export default function HomePage() {
  const { t } = useTranslation()
  const { user } = useAuth()

  return (
    <section>
      <h1 className="text-3xl font-semibold tracking-tight">{t('app.tagline')}</h1>
      <p className="mt-3 text-slate-600">
        {user ? t('home.welcome', { email: user.email }) : t('home.guest')}
      </p>
      <p className="mt-1 text-slate-400">{t('home.catalogSoon')}</p>
    </section>
  )
}
