import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../services/auth.jsx'

export default function Header() {
  const { t } = useTranslation()
  const { user, logout } = useAuth()

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <Link to="/" className="text-xl font-semibold tracking-tight">
          {t('app.name')}
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/market" className="rounded-md px-3 py-1.5 hover:bg-slate-100">{t('nav.market')}</Link>
          {user ? (
            <>
              {user.role === 'seller' && (
                <Link to="/seller" className="rounded-md px-3 py-1.5 hover:bg-slate-100">{t('nav.seller')}</Link>
              )}
              <span className="text-slate-500">
                {user.email} · {t(`roles.${user.role}`)}
              </span>
              <button onClick={logout} className="rounded-md px-3 py-1.5 hover:bg-slate-100">
                {t('nav.logout')}
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="rounded-md px-3 py-1.5 hover:bg-slate-100">
                {t('nav.login')}
              </Link>
              <Link to="/register" className="rounded-md bg-slate-900 px-3 py-1.5 text-white hover:bg-slate-700">
                {t('nav.register')}
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}
