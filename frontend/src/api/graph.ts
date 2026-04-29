import client from './client'

export function fetchGraphLatest() {
  return client.get('/api/graph/latest')
}

export function fetchGraphByReport(reportId: string) {
  return client.get(`/api/graph/${reportId}`)
}

export function queryGraph(params: Record<string, any>) {
  return client.post('/api/graph/query', params)
}
