import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { ErrorText } from '../components/AuthForm'
import api, { errorKey } from '../services/api'

const STORE_FIELDS = ['name', 'inn_stir', 'phone', 'telegram', 'address', 'district']
const FIELD_LABELS = { inn_stir: 'innStir' }
const CURRENCIES = ['USD', 'UZS']
const ACCEPT = '.xlsx,.xls,.csv,.pdf'

function StoreForm({ store, onSaved }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(() =>
    Object.fromEntries(STORE_FIELDS.map((f) => [f, store?.[f] ?? ''])))
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSaved(false)
    // Empty optional fields are sent as null
    const payload = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]))
    try {
      const res = await api.put('/stores/me', payload)
      setSaved(true)
      onSaved(res.data)
    } catch (err) {
      setError(t(errorKey(err)))
    }
  }

  return (
    <form onSubmit={onSubmit} className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-semibold">{t('store.title')}</h2>
      {!store && <p className="mt-1 text-sm text-slate-500">{t('store.createHint')}</p>}
      {store && (
        <p className={`mt-1 text-sm ${store.is_verified ? 'text-emerald-700' : 'text-slate-500'}`}>
          {t(store.is_verified ? 'store.verified' : 'store.notVerified')}
        </p>
      )}
      <div className="mt-4 grid grid-cols-2 gap-4">
        {STORE_FIELDS.map((f) => (
          <label key={f} className="block">
            <span className="mb-1 block text-sm text-slate-600">{t(`store.${FIELD_LABELS[f] || f}`)}</span>
            <input
              value={form[f]} required={f === 'name'} minLength={f === 'name' ? 2 : undefined}
              onChange={(e) => setForm({ ...form, [f]: e.target.value })}
              className="w-full rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
            />
          </label>
        ))}
      </div>
      <div className="mt-4"><ErrorText>{error}</ErrorText></div>
      <div className="flex items-center gap-3">
        <button className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700">{t('store.save')}</button>
        {saved && <span className="text-sm text-emerald-700">{t('store.saved')}</span>}
      </div>
    </form>
  )
}

function UploadBox() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [currency, setCurrency] = useState('USD')
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0])
  }

  const onSubmit = async () => {
    setError('')
    setBusy(true)
    const body = new FormData()
    body.append('file', file)
    body.append('currency', currency)
    try {
      const res = await api.post('/imports', body)
      navigate(`/seller/imports/${res.data.id}`)
    } catch (err) {
      setError(t(errorKey(err)))
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-semibold">{t('upload.title')}</h2>
      <div
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`mt-4 cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition ${
          dragging ? 'border-slate-900 bg-slate-50' : 'border-slate-300 hover:border-slate-400'}`}
      >
        <p className="font-medium">{file ? file.name : t('upload.drop')}</p>
        <p className="mt-1 text-sm text-slate-500">{t('upload.formats')}</p>
        <input ref={inputRef} type="file" accept={ACCEPT} hidden
          onChange={(e) => e.target.files[0] && setFile(e.target.files[0])} />
      </div>
      <div className="mt-4 flex items-center gap-4">
        <span className="text-sm text-slate-600">{t('upload.currency')}</span>
        {CURRENCIES.map((c) => (
          <label key={c} className="flex items-center gap-1.5 text-sm">
            <input type="radio" name="currency" checked={currency === c} onChange={() => setCurrency(c)} />
            {c}
          </label>
        ))}
      </div>
      <div className="mt-4"><ErrorText>{error}</ErrorText></div>
      <button
        onClick={onSubmit} disabled={!file || busy}
        className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {busy ? t('auth.loading') : t('upload.submit')}
      </button>
    </div>
  )
}

function ImportHistory() {
  const { t } = useTranslation()
  const [items, setItems] = useState([])

  useEffect(() => {
    api.get('/imports').then((res) => setItems(res.data)).catch(() => {})
  }, [])

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-semibold">{t('upload.history')}</h2>
      {items.length === 0 && <p className="mt-2 text-sm text-slate-500">{t('upload.empty')}</p>}
      <ul className="mt-2 divide-y divide-slate-100">
        {items.map((imp) => (
          <li key={imp.id} className="flex items-center justify-between py-2 text-sm">
            <Link to={`/seller/imports/${imp.id}`} className="font-medium hover:underline">{imp.filename}</Link>
            <span className="text-slate-500">
              {imp.currency} · {new Date(imp.created_at).toLocaleString('ru-RU')} · {t(`import.status.${imp.status}`)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function SellerPage() {
  const [store, setStore] = useState(undefined)

  useEffect(() => {
    api.get('/stores/me').then((res) => setStore(res.data)).catch(() => setStore(null))
  }, [])

  if (store === undefined) return null
  return (
    <div className="grid gap-6">
      <StoreForm store={store} onSaved={setStore} />
      {store && <UploadBox />}
      {store && <ImportHistory />}
    </div>
  )
}
