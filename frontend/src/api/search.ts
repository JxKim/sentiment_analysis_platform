import client from './client'

export function search(query: string) {
  return client.post('/api/search', { query })
}
