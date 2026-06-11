import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    console.error('[API Error]', err.message, err.response?.status)
    return Promise.reject(err)
  }
)

export const artifactApi = {
  list: (params = {}) => api.get('/artifacts', { params }),
  get: (id) => api.get(`/artifacts/${id}`),
  realtime: (id) => api.get(`/artifacts/${id}/realtime`),
  realtimeAll: (params = {}) => api.get('/artifacts/realtime/all', { params }),
  trends: (id, metric, hours = 24) =>
    api.get(`/artifacts/${id}/trends`, { params: { metric, hours } }),
  predictions: (id) => api.get(`/artifacts/${id}/predictions`),
  riskZones: (id) => api.get(`/artifacts/${id}/risk-zones`)
}

export const sensorApi = {
  list: (params = {}) => api.get('/sensors', { params })
}

export const alertApi = {
  list: (params = {}) => api.get('/alerts', { params }),
  acknowledge: (id, operator) =>
    api.post(`/alerts/${id}/acknowledge`, { operator }),
  resolve: (id, notes) => api.post(`/alerts/${id}/resolve`, { notes })
}

export const sprayApi = {
  list: (params = {}) => api.get('/spray-tasks', { params }),
  optimize: (payload) => api.post('/spray-tasks/optimize', payload),
  execute: (id) => api.post(`/spray-tasks/${id}/execute`)
}

export const statsApi = {
  get: () => api.get('/statistics')
}

export const ingestApi = {
  direct: (sensorType, payload) => api.post(`/ingest/${sensorType}`, payload)
}

export default api
