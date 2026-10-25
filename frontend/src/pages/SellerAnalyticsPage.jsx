import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import { DemoNote, IndexSection, MarketLabel, ProductLink } from '../components/Market'
import api, { errorKey } from '../services/api'
import { formatPrice, roundSum } from '../services/format'

const COUNT_STYLE = { below: 'text-emerald-700', at: 'text-slate-700', above: 'text-amber-800' }

export default function SellerAnalyticsPage() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState('quarter')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/seller/analytics', { params: { period } })
      .then((res) => { setData(res.data); setError('') })
      .catch((err) => setError(t(errorKey(err))))
  }, [period, t])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!data) return null
  const sum = (usd) => (data.usd_rate ? `≈ ${formatPrice(roundSum(usd * data.usd_rate), 'UZS')}` : formatPrice(usd, 'USD'))
  const { counts, gaps, no_data: noData } = data.position

  return (
    <div className="grid gap-6">
      <div>
        <Link to="/seller" className="text-sm text-slate-500 hover:underline">← {t('nav.seller')}</Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{t('market.analyticsTitle')}</h1>
        <p className="mt-1 text-slate-500">{t('market.analyticsHint')}</p>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="flex items-center gap-2 text-lg font-semibold">{t('market.positionTitle')} <DemoNote show={data.includes_demo} /></h2>
        <p className="mt-1 text-sm text-slate-500">{t('market.positionHint')}</p>
        <div className="mt-4 grid grid-cols-4 gap-4">
          {['below', 'at', 'above'].map((k) => (
            <div key={k} className="rounded-lg bg-slate-50 p-4">
              <p className={`text-2xl font-semibold ${COUNT_STYLE[k]}`}>{counts[k]}</p>
              <p className="text-sm text-slate-600">{t(`market.counts.${k}`)}</p>
            </div>
          ))}
          <div className="rounded-lg bg-slate-50 p-4">
            <p className="text-2xl font-semibold text-slate-400">{noData}</p>
            <p className="text-sm text-slate-600">{t('market.counts.noData')}</p>
          </div>
        </div>
        <h3 className="mt-6 font-medium">{t('market.gapsTitle')}</h3>
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 font-normal">{t('market.table.product')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.yourPrice')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.market')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.stores')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.diff')}</th>
            </tr>
          </thead>
          <tbody>
            {gaps.map((g) => (
              <tr key={`${g.id}-${g.condition}`} className="border-t border-slate-100">
                <td className="py-1.5 pr-4"><ProductLink item={g} />{g.condition !== 'new' && <span className="text-slate-500"> · {t(`condition.${g.condition}`)}</span>}</td>
                <td className="py-1.5 text-right whitespace-nowrap">{sum(g.price_usd)}</td>
                <td className="py-1.5 text-right whitespace-nowrap">{sum(g.market_usd)}</td>
                <td className="py-1.5 text-right text-slate-500">{g.stores}</td>
                <td className="py-1.5 text-right whitespace-nowrap"><MarketLabel info={g} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="text-lg font-semibold">{t('market.missingTitle')}</h2>
        <p className="mt-1 text-sm text-slate-500">{t('market.missingHint')}</p>
        {data.missing.length === 0 ? <p className="mt-3 text-sm text-slate-500">{t('market.missingNone')}</p> : (
          <ol className="mt-3 grid gap-1.5 text-sm">
            {data.missing.map((m, i) => (
              <li key={m.id} className="flex justify-between gap-4 border-t border-slate-100 pt-1.5">
                <span><span className="mr-2 text-slate-400">{i + 1}.</span><ProductLink item={m} /> <span className="text-slate-500">· {t(`categories.${m.category}`)}</span></span>
                <span className="whitespace-nowrap text-slate-600">{t('market.storesCount', { count: m.stores })} · {sum(m.market_usd)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <IndexSection indices={data.indices} period={period} onPeriod={setPeriod} demo={data.includes_demo} />
    </div>
  )
}
