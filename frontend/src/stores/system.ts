import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as systemApi from '@/api/system'

export const useSystemStore = defineStore('system', () => {
  const started = ref(false)
  const starting = ref(false)
  const connectionStatus = ref<'connected' | 'disconnected'>('disconnected')
  const shutdownInProgress = ref(false)

  async function fetchStatus() {
    try {
      const res = await systemApi.fetchSystemStatus()
      started.value = res.data.started
      starting.value = res.data.starting
    } catch {
      // ignore
    }
  }

  async function startSystem() {
    starting.value = true
    try {
      const res = await systemApi.startSystem()
      if (res.data.success) {
        started.value = true
      }
      starting.value = false
      return res.data
    } catch {
      starting.value = false
      return null
    }
  }

  async function shutdownSystem() {
    try {
      const res = await systemApi.shutdownSystem()
      if (res.data.success) {
        shutdownInProgress.value = true
        started.value = false
      }
      return res.data
    } catch {
      return null
    }
  }

  return {
    started, starting, connectionStatus, shutdownInProgress,
    fetchStatus, startSystem, shutdownSystem,
  }
})
