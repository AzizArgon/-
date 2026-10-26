import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes } from 'react-router-dom'
import Header from './components/Header'
import CatalogPage from './pages/CatalogPage'
import ImportPage from './pages/ImportPage'
import LoginPage from './pages/LoginPage'
import MarketPage from './pages/MarketPage'
import ProductPage from './pages/ProductPage'
import RegisterPage from './pages/RegisterPage'
import SellerAnalyticsPage from './pages/SellerAnalyticsPage'
import SellerPage from './pages/SellerPage'
import { useAuth } from './services/auth.jsx'

// Pages for guests only: logged-in users are sent home
function GuestOnly({ children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Navigate to="/" replace /> : children
}

// Pages for one role only: others are sent home
function RoleOnly({ role, children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  return user?.role === role ? children : <Navigate to="/" replace />
}

const GITHUB_URL = 'https://github.com/AzizArgon/-'
// Set only for the public server build (deploy.bat)
const PUBLIC_DEMO = import.meta.env.VITE_PUBLIC_DEMO === '1'

function DemoBanner() {
  const { t } = useTranslation()
  return (
    <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-center text-sm text-amber-900">
      {t('demo.banner')}
    </div>
  )
}

function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="border-t border-slate-200">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-6 text-sm text-slate-500">
        <span>{t('demo.footer')}</span>
        <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="shrink-0 font-medium text-slate-700 hover:underline">
          {t('demo.github')}
        </a>
      </div>
    </footer>
  )
}

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      {PUBLIC_DEMO && <DemoBanner />}
      <Header />
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-10">
        <Routes>
          <Route path="/" element={<CatalogPage />} />
          <Route path="/products/:id" element={<ProductPage />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="/register" element={<GuestOnly><RegisterPage /></GuestOnly>} />
          <Route path="/seller" element={<RoleOnly role="seller"><SellerPage /></RoleOnly>} />
          <Route path="/seller/analytics" element={<RoleOnly role="seller"><SellerAnalyticsPage /></RoleOnly>} />
          <Route path="/seller/imports/:id" element={<RoleOnly role="seller"><ImportPage /></RoleOnly>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}
