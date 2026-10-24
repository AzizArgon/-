import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import api, { errorKey } from '../services/api'

const PAGE_SIZE = 50
const POLL_MS = 2000
const CONDITIONS = ['new', 'used', 'refurbished']

// Rows the seller should look at: no price, unknown category or no brand
const needsAttention = (r) => r.price == null || r.category === 'other' || !r.brand

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

function PreviewTable({ rows, setRows, categories, currency, readOnly }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [page, setPage] = useState(1)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((r) =>
      (!onlyIssues || needsAttention(r)) &&
      (!q || r.name.toLowerCase().includes(q) || r.raw_name.toLowerCase().includes(q)))
  }, [rows, query, onlyIssues])

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const current = Math.min(page, pages)
  const pageRows = visible.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)

  const edit = (rowId, field, value) =>
    setRows(rows.map((r) => {
      if (r.row !== rowId) return r
      const next = { ...r, [field]: value }
      if (field === 'price') next.is_in_stock = value != null
      return next
    }))

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
        <span className="ml-auto text-slate-500">{t('import.rows', { count: visible.length })}</span>
      </div>
      <table className="w-full table-fixed text-sm">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr>
            <th className="w-[34%] px-3 py-2 font-medium">{t('import.col.name')}</th>
            <th className="w-[11%] px-3 py-2 font-medium">{t('import.col.brand')}</th>
            <th className="w-[15%] px-3 py-2 font-medium">{t('import.col.category')}</th>
            <th className="w-[11%] px-3 py-2 font-medium">{t('import.col.price')}, {currency}</th>
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
                  {t('import.original')}: {r.raw_name}
                </p>
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
              </td>
              <td className="px-2 py-1.5 align-top">
                <select className={cellInput} disabled={readOnly} value={r.condition} onChange={(e) => edit(r.row, 'condition', e.target.value)}>
                  {CONDITIONS.map((c) => <option key={c} value={c}>{t(`condition.${c}`)}</option>)}
                </select>
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

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => {})
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
  }, [id, t])

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

  const partialFailed = imp?.error?.startsWith('chunks_failed:') ? imp.error.split(':')[1] : null

  return (
    <div className="grid gap-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/seller" className="text-sm text-slate-500 hover:underline">← {t('import.back')}</Link>
          <h1 className="mt-1 text-2xl font-semibold">{t('import.title')}{imp && `: ${imp.filename}`}</h1>
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
        <ErrorText>{t(imp.error === 'ai_quota' ? 'import.quota' : 'import.failed')}</ErrorText>
      )}
      {imp?.status === 'published' && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">
          <p className="font-medium">{t('import.published')}</p>
          {stats && <p className="mt-1 text-sm">{t('import.publishedStats', stats)}</p>}
        </div>
      )}
      {imp?.status === 'ready' && (
        <>
          {partialFailed && <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{t('import.partial', { count: partialFailed })}</p>}
          <p className="text-sm text-slate-500">{t('import.hint')}</p>
        </>
      )}
      {(imp?.status === 'ready' || imp?.status === 'published') && rows.length > 0 && (
        <PreviewTable rows={rows} setRows={setRows} categories={categories}
          currency={imp.currency} readOnly={imp.status !== 'ready'} />
      )}
    </div>
  )
}
