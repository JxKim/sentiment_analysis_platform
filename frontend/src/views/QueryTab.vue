<template>
  <div class="tab-content">
    <IframePanel
      ref="iframeRef"
      app-name="Query Engine"
      :port="8503"
      :running="appsStore.apps.query?.status === 'running'"
      :auto-search="searchStore.query"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import IframePanel from '@/components/shared/IframePanel.vue'
import { useAppsStore } from '@/stores/apps'
import { useSearchStore } from '@/stores/search'

const appsStore = useAppsStore()
const searchStore = useSearchStore()
const iframeRef = ref<InstanceType<typeof IframePanel> | null>(null)

defineExpose({ iframeRef })
</script>

<style scoped>
.tab-content { width: 100%; height: 100%; }
</style>
