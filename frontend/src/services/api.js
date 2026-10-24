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

// Maps an axios error to an i18n key from the "errors" section
export function errorKey(err) {
  if (!err.response) return 'errors.network'
  switch (err.response.status) {
    case 401: return 'errors.invalidCredentials'
    case 409: return 'errors.emailTaken'
    case 422: return 'errors.validation'
    default: return 'errors.unknown'
  }
}

export default api
