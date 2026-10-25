import i18n from '../i18n'

// Prices: "$1 234.50" for USD, "1 234 567 сум" for UZS (currency word comes from the translations)
export function formatPrice(value, currency) {
  if (value == null) return '—'
  const locale = i18n.language || 'ru'
  if (currency === 'USD') {
    return '$' + new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)} ${i18n.t('currency.UZS')}`
}

export function formatDate(iso) {
  return new Intl.DateTimeFormat(i18n.language || 'ru').format(new Date(iso))
}

// "@store", "t.me/store" or "https://t.me/store" -> https://t.me/store
export function telegramUrl(handle) {
  const name = handle.trim().replace(/^(https?:\/\/)?(t\.me\/)?@?/, '')
  return `https://t.me/${name}`
}
