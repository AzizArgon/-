import { useTranslation } from 'react-i18next'

const FLAG_STYLE = {
  info: 'border-sky-200 bg-sky-50 text-sky-800',
  warning: 'border-amber-300 bg-amber-50 text-amber-900',
  danger: 'border-red-300 bg-red-50 text-red-800',
}
const FLAG_ICON = { info: 'ℹ', warning: '⚠', danger: '⛔' }

// Anti-Fraud badges: the server sends a reason key + params, the soft text is in the translations
export default function Flags({ flags, className = 'mt-1 grid gap-1 px-1.5' }) {
  const { t } = useTranslation()
  if (!flags?.length) return null
  return (
    <div className={className}>
      {flags.map((f) => (
        <p key={f.type} className={`rounded border px-2 py-1 text-xs ${FLAG_STYLE[f.level]}`}>
          <span className="font-medium">{FLAG_ICON[f.level]} {t(`flags.type.${f.type}`)}</span>
          {f.source === 'ai' && <span className="opacity-70"> ({t('flags.ai')})</span>}
          {' — '}{t(`flags.reason.${f.reason_key}`, f.params)}
        </p>
      ))}
    </div>
  )
}
