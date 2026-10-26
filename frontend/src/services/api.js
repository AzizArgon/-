import axios from 'axios'

export const TOKEN_KEY = 'pc_market_token'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api',
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Maps an axios error to an i18n key from the "errors" section.
// `overrides` lets a page give its own meaning to a status code, e.g. { 409: 'errors.importNotReady' }
export function errorKey(err, overrides = {}) {
  if (!err.response) return 'errors.network'
  if (overrides[err.response.status]) return overrides[err.response.status]
  // Limits of the public demo answer with a code: { detail: { code: 'import_limit_store' } }
  const code = err.response.data?.detail?.code
  if ([403, 429].includes(err.response.status) && code) return `errors.${code}`
  switch (err.response.status) {
    case 401: return 'errors.invalidCredentials'
    case 404: return 'errors.notFound'
    case 409: return 'errors.emailTaken'
    case 413: return 'errors.fileTooLarge'
    case 415: return 'errors.fileType'
    case 422: return 'errors.validation'
    default: return 'errors.unknown'
  }
}

export default api
