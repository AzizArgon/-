import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import api, { errorKey } from '../services/api'
import Price from '../components/Price'
import { formatDayMonth, formatPrice } from '../services/format'
import { formatSpec, fromUrlValue, specLabel, specsLine, urlValue } from '../services/specs'

const CONDITIONS = ['new', 'new_openbox', 'used', 'refurbished', 'unknown']

const SEARCH_DELAY_MS = 300
const VISIBLE_VALUES = 8
const SPEC_PREFIX = 'f_' // spec filters in the address: ?category=ram&f_type=DDR5,DDR4&f_form_factor=SODIMM
const inputClass = 'rounded-md border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900'

function ProductTile({ item, usdRate, rateDate }) {
  const { t } = useTranslation()
  return (
    <Link to={`/products/${item.id}`}
      className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 hover:border-slate-400 hover:shadow-sm">
      <span className="text-xs text-slate-500">{t(`categories.${item.category}`)}</span>
      <span className="mt-1 line-clamp-3 font-medium leading-snug">{item.name}</span>
      {item.specs?.length > 0 && <span className="mt-1 text-sm text-slate-600">{specsLine(item.specs)}</span>}
      <div className="mt-auto pt-3">
        <Price price={item.min_price} currency={item.min_currency} usdRate={usdRate} rateDate={rateDate}
          prefix={`${t('catalog.from')} `} size="text-lg" />
        <span className="block text-sm text-slate-500">{t('catalog.offers', { count: item.offers })}</span>
      </div>
    </Link>
  )
}

// One filter of the category: ticks with counts ("DDR5 (124)"), or "from N" for refresh rate and power
function Facet({ facet, category, selected, onToggle, onAtLeast }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const label = specLabel(facet.key, category)
  const format = (value) => formatSpec({ ...facet, value })

  if (facet.at_least) {
    // "from 144 Hz" counts every product with 144 Hz and more
    const atLeast = (v) => facet.values.filter((x) => x.value >= v).reduce((sum, x) => sum + x.count, 0)
    return (
      <div>
        <p className="mb-1 text-sm font-medium">{label}</p>
        <select value={selected[0] || ''} onChange={(e) => onAtLeast(e.target.value)} className={`${inputClass} w-full py-1.5 text-sm`}>
          <option value="">{t('catalog.any')}</option>
          {facet.values.map(({ value }) => (
            <option key={value} value={urlValue(value)}>{t('catalog.atLeast', { value: format(value) })} ({atLeast(value)})</option>
          ))}
        </select>
      </div>
    )
  }
  const values = open ? facet.values : facet.values.slice(0, VISIBLE_VALUES)
  return (
    <div>
      <p className="mb-1 text-sm font-medium">{label}</p>
      {values.map(({ value, count }) => (
        <label key={urlValue(value)} className="flex items-center gap-2 py-0.5 text-sm">
          <input type="checkbox" checked={selected.includes(urlValue(value))} onChange={() => onToggle(urlValue(value))} />
          <span>{format(value)} <span className="text-slate-400">({count})</span></span>
        </label>
      ))}
      {facet.values.length > VISIBLE_VALUES && (
        <button onClick={() => setOpen(!open)} className="mt-0.5 text-sm text-slate-500 hover:underline">
          {open ? t('catalog.showLess') : t('catalog.showAll', { count: facet.values.length })}
        </button>
      )}
    </div>
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
  const category = params.get('category') || ''

  // Ticks add a history step (browser "back" undoes them); typing in a field replaces the current one
  const update = (change, push = false) => {
    const next = new URLSearchParams(params)
    change(next)
    next.delete('page')
    setParams(next, { replace: !push })
  }
  const setParam = (key, value, push = false) => update((next) => {
    if (value === '' || value == null) next.delete(key)
    else next.set(key, value)
  }, push)
  const specKeys = [...params.keys()].filter((k) => k.startsWith(SPEC_PREFIX))
  const selectedOf = (key) => (params.get(SPEC_PREFIX + key) || '').split(',').filter(Boolean)

  const setCategory = (slug) => update((next) => {
    specKeys.forEach((k) => next.delete(k)) // filters of one category mean nothing in another
    if (slug) next.set('category', slug)
    else next.delete('category')
  }, true)
  const toggleValue = (key, value) => update((next) => {
    const current = selectedOf(key)
    const values = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    if (values.length) next.set(SPEC_PREFIX + key, values.join(','))
    else next.delete(SPEC_PREFIX + key)
  }, true)
  const resetFilters = () => update((next) => {
    specKeys.forEach((k) => next.delete(k))
    next.delete('price_min')
    next.delete('price_max')
  }, true)

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
  const facets = (category && data?.facets) || []

  // Chips of everything selected, each removes its own value
  const chips = specKeys.flatMap((k) => {
    const key = k.slice(SPEC_PREFIX.length)
    const facet = facets.find((f) => f.key === key) || { key, kind: 'choice' }
    return selectedOf(key).map((v) => {
      const value = formatSpec({ ...facet, value: fromUrlValue(facet.kind, v) })
      return {
        id: `${k}=${v}`,
        text: `${specLabel(key, category)}: ${facet.at_least ? t('catalog.atLeast', { value }) : value}`,
        remove: () => toggleValue(key, v),
      }
    })
  })
  for (const [k, word] of [['price_min', 'priceMin'], ['price_max', 'priceMax']]) {
    if (params.get(k)) {
      chips.push({ id: k, text: `${t('catalog.price')}: ${t(`catalog.${word}`)} ${formatPrice(Number(params.get(k)), 'UZS')}`,
        remove: () => setParam(k, '', true) })
    }
  }

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('app.tagline')}</h1>

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('catalog.searchPlaceholder')}
          className={`${inputClass} min-w-80 flex-1`} autoFocus />
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={inputClass}>
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
        <select value={params.get('condition') || ''} onChange={(e) => setParam('condition', e.target.value, true)} className={inputClass}>
          <option value="">{t('catalog.anyCondition')}</option>
          {CONDITIONS.map((c) => <option key={c} value={c}>{t(`condition.${c}`)}</option>)}
        </select>
        <label className="flex items-center gap-2 py-2 text-sm">
          <input type="checkbox" checked={!params.get('all')} onChange={(e) => setParam('all', e.target.checked ? '' : '1', true)} />
          {t('catalog.inStockOnly')}
        </label>
      </div>

      <div className="mt-4"><ErrorText>{error}</ErrorText></div>
      {data && (
        <div className="flex items-start gap-6">
          {facets.length > 0 && (
            <aside className="w-60 shrink-0 space-y-4 rounded-xl border border-slate-200 bg-white p-4" aria-label={t('catalog.filters')}>
              <p className="font-semibold">{t('catalog.filters')}</p>
              {facets.map((f) => (
                <Facet key={f.key} facet={f} category={category} selected={selectedOf(f.key)}
                  onToggle={(v) => toggleValue(f.key, v)} onAtLeast={(v) => setParam(SPEC_PREFIX + f.key, v, true)} />
              ))}
            </aside>
          )}
          <div className="min-w-0 flex-1">
            {chips.length > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {chips.map((c) => (
                  <button key={c.id} onClick={c.remove}
                    className="rounded-full bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700">{c.text} ✕</button>
                ))}
                <button onClick={resetFilters} className="text-sm text-slate-600 underline hover:text-slate-900">{t('catalog.reset')}</button>
              </div>
            )}
            <p className="text-sm text-slate-500">
              {t('catalog.found', { count: data.total })}
              {data.usd_rate && <> · {t('price.rateNote', { date: formatDayMonth(data.usd_rate_date), rate: formatPrice(data.usd_rate, 'UZS') })}</>}
            </p>
            {data.items.length === 0 ? (
              <p className="mt-6 text-slate-500">{t('catalog.empty')}</p>
            ) : (
              <div className={`mt-4 grid gap-4 ${facets.length > 0 ? 'grid-cols-3' : 'grid-cols-4'}`}>
                {data.items.map((item) => <ProductTile key={item.id} item={item} usdRate={data.usd_rate} rateDate={data.usd_rate_date} />)}
              </div>
            )}
            {pages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-3 text-sm">
                <button disabled={page <= 1} onClick={() => setParams((p) => { p.set('page', page - 1); return p })}
                  className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40">{t('catalog.prev')}</button>
                <span>{t('catalog.page', { page, pages })}</span>
                <button disabled={page >= pages} onClick={() => setParams((p) => { p.set('page', page + 1); return p })}
                  className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40">{t('catalog.next')}</button>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
