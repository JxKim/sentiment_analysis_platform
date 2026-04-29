import client from './client'

export function fetchSystemStatus() {
  return client.get('/api/system/status')
}

export function startSystem() {
  return client.post('/api/system/start')
}

export function shutdownSystem() {
  return client.post('/api/system/shutdown')
}
