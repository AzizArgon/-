import { useEffect, useState } from 'react'
import api from './api'
import i18n from '../i18n'

// Characteristics come from the dictionary as { key, kind, unit, value }: 16 + "GB" -> "16 ГБ", 1000 GB -> "1 ТБ"

// Key name; some keys read differently in a category ("type" of RAM is "Тип памяти")
export function specLabel(key, category) {
  return i18n.t([`specs.label.${category}.${key}`, `specs.${key}`], { defaultValue: key })
}

export function formatSpec({ key, kind, unit, value }) {
  if (kind === 'yesno' || typeof value === 'boolean') return i18n.t(value ? 'specs.yes' : 'specs.no')
  if (kind === 'number') {
    const [v, u] = unit === 'GB' && value >= 1000 ? [value / 1000, 'TB'] : [value, unit]
    const num = new Intl.NumberFormat(i18n.language || 'ru', { maximumFractionDigits: 1, useGrouping: v >= 10000 }).format(v) // "6000 МГц", "10 000 ВА"
    return i18n.t(`specs.unit.${u}`, { count: v, value: num, defaultValue: `${num} ${u}` })
  }
  // Values with dots ("M.2", "2.5\"") can't be i18n key parts: the value names are read as one object
  const names = i18n.t(`specs.values.${key}`, { returnObjects: true })
  if (names && typeof names === 'object' && names[value]) return names[value]
  return key === 'resolution' ? String(value).replace('x', '×') : String(value)
}

// One line for a catalog tile: "DDR5 · 16 ГБ · 6000 МГц · SODIMM"
export const specsLine = (specs) => (specs || []).map(formatSpec).join(' · ')

// Value as it is written in the page address: true -> "1", 16 -> "16"
export const urlValue = (value) => (typeof value === 'boolean' ? (value ? '1' : '0') : String(value))

export function fromUrlValue(kind, text) {
  if (kind === 'number') return Number(text)
  if (kind === 'yesno') return text === '1'
  return text
}

// The dictionary itself (keys, kinds, units by category): loaded once, for pages that get plain spec objects
let dictionaryRequest
export function useSpecDictionary() {
  const [dictionary, setDictionary] = useState(null)
  useEffect(() => {
    dictionaryRequest ||= api.get('/spec-dictionary').then((res) => res.data)
    dictionaryRequest.then(setDictionary).catch(() => { dictionaryRequest = null })
  }, [])
  return dictionary
}

// {capacity: 16, type: "DDR5"} of a category -> "Тип памяти: DDR5 · Объём: 16 ГБ"
export function specsText(category, specs, dictionary) {
  const known = Object.fromEntries((dictionary?.[category] || []).map((s) => [s.key, s]))
  const inferred = specs?._inferred || {} // values added by a rule, not written by the seller: marked with "*"
  return Object.entries(specs || {})
    .filter(([key]) => !key.startsWith('_'))
    .map(([key, value]) => `${specLabel(key, category)}: ${known[key] ? formatSpec({ ...known[key], value }) : value}`
      + (inferred[key] ? '*' : ''))
    .join(' · ')
}
