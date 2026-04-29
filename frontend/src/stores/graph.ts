import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as graphApi from '@/api/graph'
import * as configApi from '@/api/config'

export interface GraphNode {
  id: string
  label: string
  group?: string
  [key: string]: any
}

export interface GraphEdge {
  from: string
  to: string
  label?: string
  [key: string]: any
}

export const useGraphStore = defineStore('graph', () => {
  const enabled = ref(false)
  const nodes = ref<GraphNode[]>([])
  const edges = ref<GraphEdge[]>([])
  const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const taskId = ref<string | null>(null)
  const selectedNode = ref<GraphNode | null>(null)
  const searchQuery = ref('')
  const searchMatchIndex = ref(-1)
  const searchMatchTotal = ref(0)

  async function checkEnabled() {
    try {
      const res = await configApi.fetchConfig()
      if (res.data.success) {
        enabled.value = res.data.config.GRAPHRAG_ENABLED === 'true'
      }
    } catch { /* ignore */ }
  }

  async function fetchLatestGraph() {
    state.value = 'loading'
    try {
      const res = await graphApi.fetchGraphLatest()
      if (res.data.success) {
        const data = res.data.graph_data || res.data
        nodes.value = data.nodes || []
        edges.value = data.edges || []
        state.value = 'ready'
      } else {
        state.value = 'error'
      }
      return res.data
    } catch {
      state.value = 'error'
      return null
    }
  }

  async function fetchGraphByReport(reportId: string) {
    state.value = 'loading'
    taskId.value = reportId
    try {
      const res = await graphApi.fetchGraphByReport(reportId)
      if (res.data.success) {
        const data = res.data.graph_data || res.data
        nodes.value = data.nodes || []
        edges.value = data.edges || []
        state.value = 'ready'
      } else {
        state.value = 'error'
      }
      return res.data
    } catch {
      state.value = 'error'
      return null
    }
  }

  function selectNode(node: GraphNode | null) {
    selectedNode.value = node
  }

  function clearSearch() {
    searchQuery.value = ''
    searchMatchIndex.value = -1
    searchMatchTotal.value = 0
  }

  return {
    enabled, nodes, edges, state, taskId, selectedNode, searchQuery, searchMatchIndex, searchMatchTotal,
    checkEnabled, fetchLatestGraph, fetchGraphByReport, selectNode, clearSearch,
  }
})
