import client from './client'

export function startForum() {
  return client.get('/api/forum/start')
}

export function stopForum() {
  return client.get('/api/forum/stop')
}

export function fetchForumLog() {
  return client.get('/api/forum/log')
}

export function fetchForumLogHistory(position: number, maxLines: number = 1000) {
  return client.post('/api/forum/log/history', { position, max_lines: maxLines })
}
