import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import api, { errorKey } from '../services/api'
import { specsLine } from '../services/specs'
import { ErrorText } from './AuthForm'
import Flags from './Flags'
import Price from './Price'

const CURRENCIES = ['USD', 'UZS']
const CONDITIONS = ['new', 'used', 'refurbished']
const input = 'w-full rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-slate-900'

function ProductLine({ product, rate }) {
  const { t } = useTranslation()
  return (
    <div className="min-w-0">
      <p className="truncate font-medium">{product.name}</p>
      <p className="truncate text-xs text-slate-500">
        {t(`categories.${product.category}`)}{product.specs.length > 0 && ` · ${specsLine(product.specs)}`}
      </p>
      {product.my_offer && (
        <div className="mt-1 flex items-center gap-2 text-xs text-amber-800">
          <span>{t('manual.alreadyHave')}</span>
          <Price price={product.my_offer.price} currency={product.my_offer.currency} usdRate={rate?.rate}
            rateDate={rate?.rate_date} size="text-sm" />
        </div>
      )}
    </div>
  )
}

// Price form for a chosen card: a new offer, or the price update of the store's existing one
function OfferForm({ product, defaultCurrency, rate, onDone, onConflict }) {
  const { t } = useTranslation()
  const mine = product.my_offer
  const [form, setForm] = useState({
    price: mine?.price ?? '', currency: mine?.currency ?? defaultCurrency,
    condition: mine?.condition ?? 'new', is_in_stock: mine?.is_in_stock ?? true,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const onSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api.post('/seller/offers', {
        ...form, price: Number(form.price), product_id: product.id, replace: Boolean(mine),
      })
      onDone(res.data)
    } catch (err) {
      // The store already has this card: show its offer and offer to update the price instead of a duplicate
      if (err.response?.status === 409 && err.response.data.detail?.code === 'offer_exists') {
        onConflict(err.response.data.detail.product)
      } else {
        setError(t(errorKey(err)))
      }
      setBusy(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-4 rounded-lg border border-slate-200 p-4">
      <ProductLine product={product} rate={rate} />
      {mine && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">{t('manual.updateHint')}</p>}
      <div className="mt-4 grid grid-cols-4 gap-3">
        <label className="block">
          <span className="mb-1 block text-sm text-slate-600">{t('manual.price')}</span>
          <input type="number" min="0" step="any" required autoFocus value={form.price} className={input}
            onChange={(e) => setForm({ ...form, price: e.target.value })} />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-slate-600">{t('manual.currency')}</span>
          <select value={form.currency} className={input} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-slate-600">{t('import.col.condition')}</span>
          <select value={form.condition} className={input} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
            {CONDITIONS.map((c) => <option key={c} value={c}>{t(`condition.${c}`)}</option>)}
          </select>
        </label>
        <label className="flex items-end gap-2 pb-2.5 text-sm">
          <input type="checkbox" checked={form.is_in_stock} onChange={(e) => setForm({ ...form, is_in_stock: e.target.checked })} />
          {t('import.inStock')}
        </label>
      </div>
      <div className="mt-3"><ErrorText>{error}</ErrorText></div>
      <button disabled={busy} className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50">
        {busy ? t('auth.loading') : t(mine ? 'manual.update' : 'manual.add')}
      </button>
    </form>
  )
}

// "Find in the catalog": the seller does not create a product, he adds his price to an existing card
export default function AddFromCatalog({ defaultCurrency, onAdded }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [found, setFound] = useState({ q: '', items: [] }) // suggestions of the last finished search
  const [chosen, setChosen] = useState(null)
  const [done, setDone] = useState(null)
  const [rate, setRate] = useState(null)

  useEffect(() => {
    api.get('/rates/usd').then((res) => setRate(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (q.trim().length < 2) return
    const timer = setTimeout(() => {
      api.get('/seller/catalog-search', { params: { q } }).then((res) => setFound({ q, items: res.data })).catch(() => {})
    }, 250)
    return () => clearTimeout(timer)
  }, [q])

  const items = found.q === q ? found.items : []

  const choose = (product) => {
    setChosen(product)
    setDone(null)
  }

  return (
    <div>
      <div className="relative">
        <input value={q} placeholder={t('manual.searchPlaceholder')} className={input}
          onChange={(e) => { setQ(e.target.value); setChosen(null); setDone(null) }} />
        {items.length > 0 && !chosen && (
          <ul className="absolute z-10 mt-1 max-h-96 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
            {items.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => choose(p)} className="w-full px-3 py-2 text-left hover:bg-slate-50">
                  <ProductLine product={p} rate={rate} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {found.q === q && q.trim().length >= 2 && items.length === 0 && !chosen && !done && (
          <p className="mt-2 text-sm text-slate-500">{t('manual.nothingFound')}</p>
        )}
      </div>
      {chosen && (
        <OfferForm key={`${chosen.id}-${Boolean(chosen.my_offer)}`} product={chosen} rate={rate}
          defaultCurrency={defaultCurrency} onConflict={setChosen}
          onDone={(res) => { setDone({ ...res, product: chosen }); setChosen(null); setQ(''); onAdded?.() }} />
      )}
      {done && (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm">
          <p className="text-emerald-800">
            {t(done.created ? 'manual.added' : 'manual.updated')}{' '}
            <Link to={`/products/${done.product.id}`} className="font-medium underline">{done.product.name}</Link>
          </p>
          <Flags flags={done.flags} className="mt-2 grid gap-1" />
        </div>
      )}
    </div>
  )
}
