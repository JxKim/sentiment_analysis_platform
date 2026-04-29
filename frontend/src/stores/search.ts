import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as searchApi from '@/api/search'

export const useSearchStore = defineStore('search', () => {
  const query = ref('')
  const searching = ref(false)
  const lastResult = ref<any>(null)

  async function performSearch(q: string) {
    query.value = q
    searching.value = true
    try {
      const res = await searchApi.search(q)
      lastResult.value = res.data
      return res.data
    } finally {
      searching.value = false
    }
  }

  return { query, searching, lastResult, performSearch }
})
