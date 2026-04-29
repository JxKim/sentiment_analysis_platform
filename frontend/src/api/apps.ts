import client from './client'

export function fetchAppStatus() {
  return client.get('/api/status')
}

export function startApp(name: string) {
  return client.get(`/api/start/${name}`)
}

export function stopApp(name: string) {
  return client.get(`/api/stop/${name}`)
}

export function fetchAppOutput(name: string) {
  return client.get(`/api/output/${name}`)
}

export function sendTestLog(name: string) {
  return client.get(`/api/test_log/${name}`)
}
