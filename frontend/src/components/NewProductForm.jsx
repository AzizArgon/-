import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api, { errorKey } from '../services/api'
import { formatSpec, specLabel, specsLine, useSpecDictionary } from '../services/specs'
import { ErrorText } from './AuthForm'

const input = 'w-full rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-slate-900'

// One characteristic: a list of allowed values, a number with its unit or yes/no — never free text where the
// dictionary knows the values
function SpecField({ spec, category, value, onChange }) {
  const { t } = useTranslation()
  let field
  if (spec.kind === 'number') {
    field = (
      <div className="flex items-center gap-2">
        <input type="number" min="0" step="any" value={value ?? ''} className={input}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
        <span className="shrink-0 text-sm text-slate-500">
          {formatSpec({ ...spec, value: 0 }).replace(/^0\s*/, '') /* the unit word: "ГБ", "МГц" */}
        </span>
      </div>
    )
  } else if (spec.kind === 'yesno') {
    field = (
      <select value={value == null ? '' : value ? '1' : '0'} className={input}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === '1')}>
        <option value="">—</option>
        <option value="1">{t('specs.yes')}</option>
        <option value="0">{t('specs.no')}</option>
      </select>
    )
  } else if (spec.values) {
    field = (
      <select value={value ?? ''} className={input} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>
        {spec.values.map((v) => <option key={v} value={v}>{formatSpec({ ...spec, value: v })}</option>)}
      </select>
    )
  } else {
    // Open lists (GPU chip, chipset, resolution): the spelling is fixed by the server ("rtx4060" -> "RTX 4060")
    field = <input value={value ?? ''} className={input} placeholder={t(`manual.example.${spec.key}`, { defaultValue: '' })}
      onChange={(e) => onChange(e.target.value || null)} />
  }
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate-600">{specLabel(spec.key, category)}</span>
      {field}
    </label>
  )
}

// "Not in the catalog": a new reference card. If the same card exists, the seller is offered to use it
export default function NewProductForm({ initialName, onCreated, onCancel }) {
  const { t } = useTranslation()
  const dictionary = useSpecDictionary()
  const [categories, setCategories] = useState([])
  const [form, setForm] = useState({ category: '', brand: '', model: '', name: initialName || '' })
  const [specs, setSpecs] = useState({})
  const [existing, setExisting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => {})
  }, [])

  const fields = (dictionary?.[form.category] || []).filter((s) => s.key !== 'brand')

  const onSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setExisting(null)
    const payload = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]))
    try {
      const res = await api.post('/seller/products', { ...payload, specs })
      onCreated(res.data)
    } catch (err) {
      if (err.response?.status === 409 && err.response.data.detail?.code === 'product_exists') {
        setExisting(err.response.data.detail.product)
      } else {
        setError(t(errorKey(err)))
      }
    }
    setBusy(false)
  }

  return (
    <form onSubmit={onSubmit} className="mt-4 rounded-lg border border-slate-200 p-4">
      <h3 className="font-semibold">{t('manual.newTitle')}</h3>
      <p className="mt-1 text-xs text-slate-500">{t('manual.newHint')}</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-sm text-slate-600">{t('import.col.category')}</span>
          <select required value={form.category} className={input}
            onChange={(e) => { setForm({ ...form, category: e.target.value }); setSpecs({}) }}>
            <option value="">—</option>
            {categories.map((c) => <option key={c.slug} value={c.slug}>{t(`categories.${c.slug}`)}</option>)}
          </select>
        </label>
        {['brand', 'model'].map((f) => (
          <label key={f} className="block">
            <span className="mb-1 block text-sm text-slate-600">{t(`import.col.${f}`)}</span>
            <input value={form[f]} className={input} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
          </label>
        ))}
        <label className="col-span-2 block">
          <span className="mb-1 block text-sm text-slate-600">{t('import.col.name')}</span>
          <input value={form.name} required className={input} placeholder={t('manual.namePlaceholder')}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
      </div>
      {fields.length > 0 && (
        <>
          <p className="mt-4 text-sm font-medium">{t('manual.specs')}</p>
          <div className="mt-2 grid grid-cols-3 gap-3">
            {fields.map((s) => (
              <SpecField key={s.key} spec={s} category={form.category} value={specs[s.key]}
                onChange={(v) => setSpecs({ ...specs, [s.key]: v })} />
            ))}
          </div>
        </>
      )}
      {existing && (
        <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="text-amber-900">{t('manual.exists')}</p>
          <p className="mt-1 font-medium">{existing.name}</p>
          <p className="text-xs text-slate-500">
            {t(`categories.${existing.category}`)}{existing.specs.length > 0 && ` · ${specsLine(existing.specs)}`}
          </p>
          <button type="button" onClick={() => onCreated(existing)}
            className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-white hover:bg-slate-700">{t('manual.useExisting')}</button>
        </div>
      )}
      <div className="mt-3"><ErrorText>{error}</ErrorText></div>
      <div className="flex gap-3">
        <button disabled={busy} className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50">
          {busy ? t('auth.loading') : t('manual.create')}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md px-4 py-2 text-slate-600 hover:bg-slate-100">
          {t('manual.cancel')}
        </button>
      </div>
    </form>
  )
}
