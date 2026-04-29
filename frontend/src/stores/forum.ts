import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as forumApi from '@/api/forum'

export interface ForumMessage {
  id: string
  agent: string
  content: string
  timestamp: string
  type: 'user' | 'agent' | 'system' | 'host'
}

export const useForumStore = defineStore('forum', () => {
  const messages = ref<ForumMessage[]>([])
  const engineRunning = ref(false)
  const logPosition = ref(0)
  const MAX_MESSAGES = 2000

  async function startForumEngine() {
    try {
      const res = await forumApi.startForum()
      if (res.data.success) engineRunning.value = true
      return res.data
    } catch {
      return null
    }
  }

  async function stopForumEngine() {
    try {
      const res = await forumApi.stopForum()
      if (res.data.success) engineRunning.value = false
      return res.data
    } catch {
      return null
    }
  }

  async function fetchLog() {
    try {
      const res = await forumApi.fetchForumLog()
      if (res.data.success) {
        logPosition.value = res.data.position || 0
      }
      return res.data
    } catch {
      return null
    }
  }

  function appendMessage(msg: ForumMessage) {
    messages.value.push(msg)
    if (messages.value.length > MAX_MESSAGES) {
      messages.value = messages.value.slice(-MAX_MESSAGES)
    }
  }

  function clearMessages() {
    messages.value = []
    logPosition.value = 0
  }

  return {
    messages, engineRunning, logPosition,
    startForumEngine, stopForumEngine, fetchLog, appendMessage, clearMessages,
  }
})
