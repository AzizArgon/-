import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import Flags from '../components/Flags'
import api, { errorKey } from '../services/api'
import { formatDayMonth, importTitle, formatPrice, roundSum, roundUsd } from '../services/format'
import { specsText, useSpecDictionary } from '../services/specs'

const PAGE_SIZE = 50
const POLL_MS = 2000
const CHECK_DELAY_MS = 600
const CONDITIONS = ['new', 'new_openbox', 'used', 'refurbished', 'unknown']

// Rows the seller should look at: no price, unknown category, no brand or an Anti-Fraud warning
const isFlagged = (r) => (r.flags || []).some((f) => f.level !== 'info')
const needsAttention = (r) => r.source === 'failed' || r.currency_check || r.condition === 'unknown' || Boolean(r.specs?._suspect) || r.price == null || r.category === 'other' || !r.brand || isFlagged(r)
const SOURCE_STYLE = { rule: 'text-sky-700', cache: 'text-slate-500', ai: 'text-violet-700', failed: 'text-red-600' }

const cellInput = 'w-full rounded border border-transparent bg-transparent px-1.5 py-1 hover:border-slate-300 focus:border-slate-900 focus:bg-white outline-none'

function Progress({ imp }) {
  const { t } = useTranslation()
  const pct = imp.chunks_total ? Math.round((imp.chunks_done / imp.chunks_total) * 100) : 0
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <p>{imp.chunks_total
        ? t('import.processing', { done: imp.chunks_done, total: imp.chunks_total })
        : t('import.preparing')}</p>
      <div className="mt-3 h-2 rounded bg-slate-100">
        <div className="h-2 rounded bg-slate-900 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

const rawSpecsText = (specs) => Object.entries(specs || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')

// Confirmed specs are written in the row and already normalized by the dictionary; AI guesses are shown apart
// as the AI wrote them and are never saved
function Specs({ category, specs, guess }) {
  const { t } = useTranslation()
  const dictionary = useSpecDictionary()
  const confirmed = specsText(category, specs, dictionary)
  const guessed = rawSpecsText(guess)
  // A number outside its plausible range ("DDR5 600 МГц"): not used in filters, the seller should fix the row
  const suspect = specsText(category, specs?._suspect, dictionary)
  if (!confirmed && !guessed && !suspect) return null
  return (
    <>
      {suspect && <p className="px-1.5 text-xs font-medium text-red-700">{t('import.possibleTypo')}: {suspect}</p>}
      <p className="truncate px-1.5 text-xs text-slate-500" title={[confirmed, guessed].filter(Boolean).join('\n')}>
        {confirmed}
        {guessed && (
          <span className="italic text-amber-700">{confirmed && ' · '}{t('import.aiGuess')}: {guessed}</span>
        )}
      </p>
    </>
  )
}

// Under the editable price: the other currency by the CBU rate. Sum is what buyers see first
function ConvertedPrice({ price, currency, rate }) {
  const { t } = useTranslation()
  if (price == null || !rate) return null
  const hint = t('price.rateHint', { date: formatDayMonth(rate.rate_date) })
  return currency === 'USD'
    ? <p className="px-1.5 text-xs font-medium text-slate-700" title={hint}>≈ {formatPrice(roundSum(price * rate.rate), 'UZS')}</p>
    : <p className="px-1.5 text-xs text-slate-500" title={hint}>≈ {formatPrice(roundUsd(price / rate.rate), 'USD')}</p>
}

function PreviewTable({ importId, rows, setRows, categories, currency, rate, readOnly }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const timers = useRef({})
  const [page, setPage] = useState(1)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((r) =>
      (!onlyIssues || needsAttention(r)) &&
      (!onlyFlagged || r.flags?.length > 0) &&
      (!q || r.name.toLowerCase().includes(q) || r.raw_name.toLowerCase().includes(q)))
  }, [rows, query, onlyIssues, onlyFlagged])

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const current = Math.min(page, pages)
  const pageRows = visible.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)

  // An edited row is checked by the Anti-Fraud rules again (no AI request)
  const recheck = (row) => {
    clearTimeout(timers.current[row.row])
    timers.current[row.row] = setTimeout(() =>
      api.post(`/imports/${importId}/check`, { rows: [row] })
        .then((res) => setRows((prev) => prev.map((r) => (r.row === row.row ? { ...r, flags: res.data.flags[0] } : r))))
        .catch(() => {}), CHECK_DELAY_MS)
  }

  const perRowCurrency = rows.some((r) => r.currency)

  const edit = (rowId, field, value) => {
    const next = { ...rows.find((r) => r.row === rowId), [field]: value }
    if (field === 'price') next.is_in_stock = value != null
    if (field === 'currency') next.currency_check = false // the seller looked at it
    setRows(rows.map((r) => (r.row === rowId ? next : r)))
    recheck(next)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-4 border-b border-slate-200 p-4 text-sm">
        <input value={query} placeholder={t('import.search')}
          onChange={(e) => { setQuery(e.target.value); setPage(1) }}
          className="w-72 rounded-md border border-slate-300 px-3 py-1.5 outline-none focus:border-slate-900" />
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={onlyIssues} onChange={(e) => { setOnlyIssues(e.target.checked); setPage(1) }} />
          {t('import.onlyIssues')}
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={onlyFlagged} onChange={(e) => { setOnlyFlagged(e.target.checked); setPage(1) }} />
          {t('import.onlyFlagged')}
        </label>
        <span className="ml-auto text-slate-500">{t('import.rows', { count: visible.length })}</span>
      </div>
      <table className="w-full table-fixed text-sm">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr>
            <th className="w-[34%] px-3 py-2 font-medium">{t('import.col.name')}</th>
            <th className="w-[11%] px-3 py-2 font-medium">{t('import.col.brand')}</th>
            <th className="w-[15%] px-3 py-2 font-medium">{t('import.col.category')}</th>
            {/* Pasted text: every line has its own currency, shown in the cell */}
            <th className="w-[11%] px-3 py-2 font-medium">{t('import.col.price')}{!perRowCurrency && `, ${currency}`}</th>
            <th className="w-[13%] px-3 py-2 font-medium">{t('import.col.condition')}</th>
            <th className="w-[11%] px-3 py-2 font-medium">{t('import.col.stock')}</th>
            <th className="w-[5%]" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {pageRows.map((r) => (
            <tr key={r.row} className={needsAttention(r) ? 'bg-amber-50/60' : ''}>
              <td className="px-2 py-1.5 align-top">
                <input className={`${cellInput} font-medium`} disabled={readOnly} value={r.name} required
                  onChange={(e) => edit(r.row, 'name', e.target.value)} />
                <p className="truncate px-1.5 text-xs text-slate-400" title={r.raw_name}>
                  <span className={SOURCE_STYLE[r.source] || ''}>{t(`import.source.${r.source || 'ai'}`)}</span>
                  {' · '}{t('import.original')}: {r.raw_name}
                </p>
                {r.note && <p className="truncate px-1.5 text-xs text-slate-600" title={r.note}>{t('import.note')}: {r.note}</p>}
                <Specs category={r.category} specs={r.specs} guess={r.specs_guess} />
                <Flags flags={r.flags} />
              </td>
              <td className="px-2 py-1.5 align-top">
                <input className={cellInput} disabled={readOnly} value={r.brand ?? ''}
                  onChange={(e) => edit(r.row, 'brand', e.target.value || null)} />
              </td>
              <td className="px-2 py-1.5 align-top">
                <select className={cellInput} disabled={readOnly} value={r.category} onChange={(e) => edit(r.row, 'category', e.target.value)}>
                  {categories.map((c) => <option key={c.slug} value={c.slug}>{t(`categories.${c.slug}`)}</option>)}
                </select>
              </td>
              <td className="px-2 py-1.5 align-top">
                <input className={cellInput} disabled={readOnly} type="number" min="0" step="any" value={r.price ?? ''}
                  onChange={(e) => edit(r.row, 'price', e.target.value === '' ? null : Number(e.target.value))} />
                {r.currency && (
                  <select disabled={readOnly} value={r.currency} onChange={(e) => edit(r.row, 'currency', e.target.value)}
                    className={`${cellInput} mt-1 ${r.currency_check ? 'border-amber-400 bg-amber-50' : ''}`}>
                    {['USD', 'UZS'].map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                )}
                {r.currency_check && <p className="px-1.5 text-xs text-amber-800">{t('import.checkCurrency')}</p>}
                <ConvertedPrice price={r.price} currency={r.currency || currency} rate={rate} />
              </td>
              <td className="px-2 py-1.5 align-top">
                <select className={cellInput} disabled={readOnly} value={r.condition} onChange={(e) => edit(r.row, 'condition', e.target.value)}>
                  {CONDITIONS.map((c) => <option key={c} value={c}>{t(`condition.${c}`)}</option>)}
                </select>
                {r.condition === 'unknown' && <p className="px-1.5 text-xs text-amber-800">{t('import.checkCondition')}</p>}
              </td>
              <td className={`px-3 py-2.5 align-top ${r.is_in_stock ? 'text-emerald-700' : 'text-slate-400'}`}>
                {t(r.is_in_stock ? 'import.inStock' : 'import.outOfStock')}
              </td>
              <td className="px-2 py-1.5 text-center align-top">
                <button title={t('import.remove')} hidden={readOnly} onClick={() => setRows(rows.filter((x) => x.row !== r.row))}
                  className="rounded px-2 py-1 text-slate-400 hover:bg-red-50 hover:text-red-600">✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-end gap-3 border-t border-slate-200 p-3 text-sm">
        <button disabled={current <= 1} onClick={() => setPage(current - 1)}
          className="rounded px-3 py-1 hover:bg-slate-100 disabled:opacity-40">{t('import.prev')}</button>
        <span className="text-slate-500">{t('import.page', { page: current, pages })}</span>
        <button disabled={current >= pages} onClick={() => setPage(current + 1)}
          className="rounded px-3 py-1 hover:bg-slate-100 disabled:opacity-40">{t('import.next')}</button>
      </div>
    </div>
  )
}

export default function ImportPage() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [imp, setImp] = useState(null)
  const [rows, setRows] = useState([])
  const [categories, setCategories] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [rate, setRate] = useState(null)

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => {})
    api.get('/rates/usd').then((res) => setRate(res.data)).catch(() => {})
  }, [])

  // Poll while the AI is still parsing
  useEffect(() => {
    let timer
    const load = () =>
      api.get(`/imports/${id}`)
        .then((res) => {
          setImp(res.data)
          setRows(res.data.rows)
          if (res.data.status === 'processing') timer = setTimeout(load, POLL_MS)
        })
        .catch((err) => setError(t(errorKey(err))))
    load()
    return () => clearTimeout(timer)
  }, [id, t, reloadKey])

  const publish = async () => {
    setError('')
    setBusy(true)
    try {
      const res = await api.post(`/imports/${id}/publish`, { rows })
      setStats(res.data)
      setImp({ ...imp, status: 'published' })
    } catch (err) {
      setError(t(errorKey(err, { 409: 'errors.importNotReady' })))
    } finally {
      setBusy(false)
    }
  }

  // Re-parse rows that failed (e.g. the next day, when the free AI quota is back)
  const retry = async () => {
    setError('')
    try {
      await api.post(`/imports/${id}/retry`)
      setReloadKey((k) => k + 1)
    } catch (err) {
      setError(t(errorKey(err, { 409: 'errors.importNotReady' })))
    }
  }

  // error is "rows_failed:N" or "ai_quota:N" when some rows could not be parsed
  const [failReason, failedCount] = imp?.status === 'ready' && imp.error ? imp.error.split(':') : []
  const parseStats = imp?.stats?.rows ? imp.stats : null

  return (
    <div className="grid gap-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/seller" className="text-sm text-slate-500 hover:underline">← {t('import.back')}</Link>
          <h1 className="mt-1 text-2xl font-semibold">{t('import.title')}{imp && `: ${importTitle(imp)}`}</h1>
        </div>
        {imp?.status === 'ready' && (
          <button onClick={publish} disabled={busy || rows.length === 0}
            className="rounded-md bg-slate-900 px-5 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-50">
            {busy ? t('import.publishing') : t('import.publish')}
          </button>
        )}
      </div>
      <ErrorText>{error}</ErrorText>
      {imp?.status === 'processing' && <Progress imp={imp} />}
      {imp?.status === 'failed' && (
        <ErrorText>{t([`import.error.${imp.error?.split(':')[0]}`, 'import.failed'])}</ErrorText>
      )}
      {imp?.status === 'published' && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">
          <p className="font-medium">{t('import.published')}</p>
          {stats && <p className="mt-1 text-sm">{t('import.publishedStats', stats)}</p>}
        </div>
      )}
      {imp?.status === 'ready' && (
        <>
          {failedCount && (
            <div className="flex items-center justify-between rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <span>{t(failReason === 'ai_quota' ? 'import.partialQuota' : 'import.partial', { count: failedCount })}</span>
              <button onClick={retry} className="rounded-md border border-amber-300 px-3 py-1 hover:bg-amber-100">
                {t('import.retry')}
              </button>
            </div>
          )}
          {parseStats && <p className="text-sm text-slate-500">{t('import.stats', parseStats)}</p>}
          {/* Shop remarks found in the file ("Оплата только в национальной валюте"): they do not set the currency */}
          {imp?.stats?.notices?.length > 0 && (
            <p className="mt-1 text-sm text-amber-800">{t('import.notices', { text: imp.stats.notices.join(' · ') })}</p>
          )}
          {rows.some((r) => r.flags?.length) && (
            <p className="text-sm text-amber-800">{t('import.flaggedStats', { count: rows.filter((r) => r.flags?.length).length })}</p>
          )}
          <p className="text-sm text-slate-500">{t('import.hint')}</p>
        </>
      )}
      {(imp?.status === 'ready' || imp?.status === 'published') && rows.length > 0 && (
        <PreviewTable importId={id} rows={rows} setRows={setRows} categories={categories}
          currency={imp.currency} rate={rate} readOnly={imp.status !== 'ready'} />
      )}
    </div>
  )
}
