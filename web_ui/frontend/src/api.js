import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

let csrfToken = ''

export const setAuthenticatedUser = (user) => {
  csrfToken = user?.csrf_token || ''
}

api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase()
  if (!['get', 'head', 'options'].includes(method) && csrfToken) {
    config.headers['X-CSRF-Token'] = csrfToken
  }
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      setAuthenticatedUser(null)
      window.dispatchEvent(new CustomEvent('qbt-auth-expired'))
    }
    return Promise.reject(error)
  },
)

export const login = (username, password) =>
  api.post('/auth/login', { username, password }).then(r => {
    setAuthenticatedUser(r.data.user)
    return r.data
  })
export const fetchCurrentUser = () => api.get('/auth/me').then(r => {
  setAuthenticatedUser(r.data.user)
  return r.data
})
export const logout = () => api.post('/auth/logout', {}).finally(() => setAuthenticatedUser(null))

export const fetchFactors = () => api.get('/factors').then(r => r.data)
export const fetchIndexes = () => api.get('/indexes').then(r => r.data)
export const fetchBenchmarks = () => api.get('/benchmarks').then(r => r.data)
export const fetchConfig = () => api.get('/config').then(r => r.data)
export const fetchRuns = () => api.get('/runs').then(r => r.data.runs)
export const fetchRun = (id) => api.get(`/runs/${id}`).then(r => r.data)
export const createRun = (payload) => api.post('/runs', payload).then(r => r.data)
export const cancelRun = (id) => api.post(`/runs/${id}/cancel`).then(r => r.data)
export const deleteRun = (id) => api.delete(`/runs/${id}`).then(r => r.data)
export const fetchChartData = (id, chart) => api.get(`/runs/${id}/chart-data/${chart}`).then(r => r.data.data)
export const fetchBenchmarkComparison = (id, benchmarkId) =>
  api.get(`/runs/${id}/comparison`, { params: { benchmark_id: benchmarkId } }).then(r => r.data)
export const fetchReportMarkdown = (id) => api.get(`/runs/${id}/report.md`).then(r => r.data)
export const fetchArtifacts = (id) => api.get(`/runs/${id}/artifacts`).then(r => r.data.artifacts)

// 导入因子值 (2026-08-18)
export const fetchFactorValues = () => api.get('/factor-values').then(r => r.data)
export const uploadFactorValue = (formData) =>
  api.post('/factor-values', formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
export const deleteFactorValue = (factorId) => api.delete(`/factor-values/${factorId}`).then(r => r.data)

// 历史持仓 (2026-08-18)
export const fetchLatestPositions = (id, periods = 2) =>
  api.get(`/runs/${id}/positions/latest`, { params: { periods } }).then(r => r.data)
export const positionsExportUrl = (id) => `/api/runs/${id}/positions/export`

export default api
