import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import api, { errorKey } from '../services/api'
import Price from '../components/Price'
import { formatDayMonth, formatPrice } from '../services/format'

const SEARCH_DELAY_MS = 300
const inputClass = 'rounded-md border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900'

function ProductTile({ item, usdRate, rateDate }) {
  const { t } = useTranslation()
  return (
    <Link to={`/products/${item.id}`}
      className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 hover:border-slate-400 hover:shadow-sm">
      <span className="text-xs text-slate-500">{t(`categories.${item.category}`)}</span>
      <span className="mt-1 line-clamp-3 font-medium leading-snug">{item.name}</span>
      <div className="mt-auto pt-3">
        <Price price={item.min_price} currency={item.min_currency} usdRate={usdRate} rateDate={rateDate}
          prefix={`${t('catalog.from')} `} size="text-lg" />
        <span className="block text-sm text-slate-500">{t('catalog.offers', { count: item.offers })}</span>
      </div>
    </Link>
  )
}

export default function CatalogPage() {
  const { t } = useTranslation()
  // Filters live in the URL: "back" from a product card returns to the same search
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') || '')
  const [categories, setCategories] = useState([])
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const setParam = (key, value) => {
    const next = new URLSearchParams(params)
    if (value === '' || value == null) next.delete(key)
    else next.set(key, value)
    if (key !== 'page') next.delete('page')
    setParams(next, { replace: key !== 'page' })
  }

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query !== (params.get('q') || '')) setParam('q', query.trim())
    }, SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [query]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const req = Object.fromEntries(params)
    req.in_stock = params.get('all') ? 'false' : 'true'
    delete req.all
    api.get('/catalog/products', { params: req })
      .then((res) => { setData(res.data); setError('') })
      .catch((err) => setError(t(errorKey(err))))
  }, [params, t])

  const page = data?.page || 1
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('app.tagline')}</h1>

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('catalog.searchPlaceholder')}
          className={`${inputClass} min-w-80 flex-1`} autoFocus />
        <select value={params.get('category') || ''} onChange={(e) => setParam('category', e.target.value)} className={inputClass}>
          <option value="">{t('catalog.allCategories')}</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{t(`categories.${c.slug}`)}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          {t('catalog.price')}
          <input type="number" min="0" value={params.get('price_min') || ''} placeholder={t('catalog.priceMin')}
            onChange={(e) => setParam('price_min', e.target.value)} className={`${inputClass} w-36`} step="100000" />
          <input type="number" min="0" value={params.get('price_max') || ''} placeholder={t('catalog.priceMax')}
            onChange={(e) => setParam('price_max', e.target.value)} className={`${inputClass} w-36`} step="100000" />
        </label>
        <label className="flex items-center gap-2 py-2 text-sm">
          <input type="checkbox" checked={!params.get('all')} onChange={(e) => setParam('all', e.target.checked ? '' : '1')} />
          {t('catalog.inStockOnly')}
        </label>
      </div>

      <div className="mt-4"><ErrorText>{error}</ErrorText></div>
      {data && (
        <>
          <p className="text-sm text-slate-500">
            {t('catalog.found', { count: data.total })}
            {data.usd_rate && <> · {t('price.rateNote', { date: formatDayMonth(data.usd_rate_date), rate: formatPrice(data.usd_rate, 'UZS') })}</>}
          </p>
          {data.items.length === 0 ? (
            <p className="mt-6 text-slate-500">{t('catalog.empty')}</p>
          ) : (
            <div className="mt-4 grid grid-cols-4 gap-4">
              {data.items.map((item) => <ProductTile key={item.id} item={item} usdRate={data.usd_rate} rateDate={data.usd_rate_date} />)}
            </div>
          )}
          {pages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-3 text-sm">
              <button disabled={page <= 1} onClick={() => setParam('page', page - 1)}
                className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40">{t('catalog.prev')}</button>
              <span>{t('catalog.page', { page, pages })}</span>
              <button disabled={page >= pages} onClick={() => setParam('page', page + 1)}
                className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40">{t('catalog.next')}</button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
