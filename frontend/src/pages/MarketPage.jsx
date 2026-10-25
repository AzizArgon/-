import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ErrorText } from '../components/AuthForm'
import { IndexSection, PctText, ProductLink } from '../components/Market'
import api, { errorKey } from '../services/api'
import { formatPrice, roundSum } from '../services/format'

function Movers({ title, items, sum }) {
  const { t } = useTranslation()
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      {items.length === 0 ? <p className="mt-3 text-sm text-slate-500">{t('market.notEnoughData')}</p> : (
        <ul className="mt-3 grid gap-1.5 text-sm">
          {items.map((m) => (
            <li key={m.id} className="flex justify-between gap-4 border-t border-slate-100 pt-1.5">
              <span className="min-w-0"><ProductLink item={m} /></span>
              <span className="whitespace-nowrap text-slate-600">{sum(m.from_usd)} → {sum(m.to_usd)} <PctText value={m.pct} /></span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function MarketPage() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState('quarter')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/market/overview', { params: { period } })
      .then((res) => { setData(res.data); setError('') })
      .catch((err) => setError(t(errorKey(err))))
  }, [period, t])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!data) return null
  const sum = (usd) => (data.usd_rate ? `≈ ${formatPrice(roundSum(usd * data.usd_rate), 'UZS')}` : formatPrice(usd, 'USD'))

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t('market.pageTitle')}</h1>
        <p className="mt-1 text-slate-500">{t('market.pageHint')}</p>
      </div>
      <IndexSection indices={data.indices} period={period} onPeriod={setPeriod} />
      <div className="grid grid-cols-2 gap-6">
        <Movers title={t('market.moversUp')} items={data.movers.up} sum={sum} />
        <Movers title={t('market.moversDown')} items={data.movers.down} sum={sum} />
      </div>
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="text-lg font-semibold">{t('market.archiveTitle')}</h2>
        <p className="mt-1 text-sm text-slate-500">{t('market.archiveHint')}</p>
        <table className="mt-4 w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 font-normal">{t('market.table.product')}</th>
              <th className="py-1 text-right font-normal">{t('market.archiveShort')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.now')}</th>
              <th className="py-1 text-right font-normal">{t('market.table.change')}</th>
            </tr>
          </thead>
          <tbody>
            {data.archive.map((a) => (
              <tr key={a.id} className="border-t border-slate-100">
                <td className="py-1.5 pr-4"><ProductLink item={a} /></td>
                <td className="py-1.5 text-right whitespace-nowrap">
                  {a.archive.price_uzs != null ? formatPrice(a.archive.price_uzs, 'UZS') : ''}
                  <span className="block text-xs text-slate-500">{formatPrice(a.archive.price_usd, 'USD')}</span>
                </td>
                <td className="py-1.5 text-right whitespace-nowrap">
                  {sum(a.market_usd)}
                  <span className="block text-xs text-slate-500">{formatPrice(a.market_usd, 'USD')} · {t('market.storesCount', { count: a.stores })}</span>
                </td>
                <td className="py-1.5 text-right"><PctText value={a.change_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-slate-400">{t('market.archiveNote')}</p>
      </section>
    </div>
  )
}
