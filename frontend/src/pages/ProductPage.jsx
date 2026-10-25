import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import Flags from '../components/Flags'
import api, { errorKey } from '../services/api'
import Price from '../components/Price'
import { formatDate, formatDayMonth, formatPrice, telegramUrl } from '../services/format'
import { formatSpec, specLabel } from '../services/specs'

const SORTS = ['recommended', 'price']

function Contacts({ store }) {
  const { t } = useTranslation()
  if (!store.phone && !store.telegram) return <p className="text-sm text-slate-500">{t('product.noContacts')}</p>
  return (
    <div className="flex flex-col items-end gap-1 text-sm">
      {store.phone && <a href={`tel:${store.phone}`} className="font-medium hover:underline">☎ {store.phone}</a>}
      {store.telegram && (
        <a href={telegramUrl(store.telegram)} target="_blank" rel="noreferrer" className="font-medium text-sky-700 hover:underline">
          ✈ {t('product.telegram')}
        </a>
      )}
    </div>
  )
}

function OfferRow({ offer, usdRate, rateDate }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { store } = offer

  return (
    <li className={`rounded-xl border border-slate-200 bg-white p-4 ${offer.is_in_stock ? '' : 'opacity-60'}`}>
      <div className="flex items-start gap-6">
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {store.name}
            {store.is_verified && <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">✓ {t('product.verified')}</span>}
          </p>
          <p className="text-sm text-slate-500">{[store.district, store.address].filter(Boolean).join(', ')}</p>
          <p className="mt-1 text-xs text-slate-400" title={offer.raw_name}>{offer.raw_name}</p>
          <p className="mt-1 text-sm">
            <span className={offer.is_in_stock ? 'text-emerald-700' : 'text-slate-500'}>
              {t(offer.is_in_stock ? 'product.inStock' : 'product.outOfStock')}
            </span>
            {' · '}{t(`condition.${offer.condition}`)}
            {' · '}<span className="text-slate-500">{t('product.updated', { date: formatDate(offer.updated_at) })}</span>
          </p>
        </div>
        <div className="text-right">
          <Price price={offer.price} currency={offer.currency} usdRate={usdRate} rateDate={rateDate} />
        </div>
        <div className="w-44 text-right">
          {open ? <Contacts store={store} /> : (
            <button onClick={() => setOpen(true)} className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700">
              {t('product.contact')}
            </button>
          )}
        </div>
      </div>
      <Flags flags={offer.flags} className="mt-3 grid gap-1" />
    </li>
  )
}

export default function ProductPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const [sort, setSort] = useState('recommended')
  const [product, setProduct] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get(`/catalog/products/${id}`, { params: { sort } })
      .then((res) => { setProduct(res.data); setError('') })
      .catch((err) => setError(t(errorKey(err))))
  }, [id, sort, t])

  if (error) return <ErrorText>{error}</ErrorText>
  if (!product) return null
  const specs = product.specs.filter((s) => s.key !== 'brand') // the brand has its own line

  return (
    <section>
      <button onClick={() => navigate(-1)} className="text-sm text-slate-500 hover:underline">← {t('product.back')}</button>
      <p className="mt-4 text-sm text-slate-500">
        {t(`categories.${product.category}`)}
        {product.mxik_code && <span> · {t('product.mxik')}: {product.mxik_code}</span>}
      </p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">{product.name}</h1>
      {product.brand && <p className="mt-1 text-slate-600">{t('product.brand')}: {product.brand}</p>}
      {specs.length > 0 && (
        <dl className="mt-4 grid max-w-xl grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {specs.map((s) => (
            <div key={s.key} className="contents">
              <dt className="text-slate-500">{specLabel(s.key, product.category)}</dt>
              {/* Not written by the seller: inferred by a rule, the reason is in the hover hint */}
              <dd>
                {s.inferred ? (
                  <span title={t(`specs.inferred.${s.inferred}`)} className="cursor-help border-b border-dotted border-slate-400">
                    {formatSpec(s)}<sup className="text-slate-400">*</sup>
                  </span>
                ) : formatSpec(s)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {specs.some((s) => s.inferred) && <p className="mt-1 text-xs text-slate-400">{t('product.inferredNote')}</p>}

      <div className="mt-8 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('product.offers', { count: product.offers.length })}</h2>
        <div className="flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
          {SORTS.map((s) => (
            <button key={s} onClick={() => setSort(s)}
              className={`rounded px-3 py-1.5 ${sort === s ? 'bg-slate-900 text-white' : 'hover:bg-slate-100'}`}>
              {t(`product.sort.${s}`)}
            </button>
          ))}
        </div>
      </div>
      {sort === 'recommended' && <p className="mt-1 text-sm text-slate-500">{t('product.recommendedHint')}</p>}
      {product.usd_rate && (
        <p className="mt-1 text-sm text-slate-500">{t('price.rateNote', { date: formatDayMonth(product.usd_rate_date), rate: formatPrice(product.usd_rate, 'UZS') })}</p>
      )}
      <ul className="mt-4 grid gap-3">
        {product.offers.map((o) => <OfferRow key={o.id} offer={o} usdRate={product.usd_rate} rateDate={product.usd_rate_date} />)}
      </ul>
    </section>
  )
}
