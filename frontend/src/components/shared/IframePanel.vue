<template>
  <div class="iframe-panel" ref="containerRef">
    <div v-if="!loaded" class="placeholder">
      <el-icon :size="48"><VideoPlay /></el-icon>
      <p>{{ placeholderText }}</p>
      <el-button type="primary" @click="startIframe" :loading="loading">
        启动 {{ appName }}
      </el-button>
    </div>
    <iframe
      v-show="loaded"
      ref="iframeRef"
      :src="src"
      frameborder="0"
      class="iframe-view"
      @load="onLoad"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  appName: string
  port: number
  running: boolean
  autoSearch?: string
}>(), {
  autoSearch: '',
})

const loaded = ref(false)
const loading = ref(false)

const placeholderText = computed(() => `${props.appName} Engine 未启动`)

const src = computed(() => {
  const base = `${window.location.protocol}//${window.location.hostname}:${props.port}`
  if (props.autoSearch) {
    return `${base}?query=${encodeURIComponent(props.autoSearch)}&auto_search=true`
  }
  return base
})

function startIframe() {
  loading.value = true
  // The parent should start the engine via API, then loaded becomes true
  setTimeout(() => { loading.value = false; loaded.value = true }, 1000)
}

function onLoad() {
  loaded.value = true
}

function refresh(query?: string) {
  loaded.value = true
  if (query) {
    const iframe = document.querySelector('.iframe-view') as HTMLIFrameElement
    if (iframe) {
      iframe.src = `${window.location.protocol}//${window.location.hostname}:${props.port}?query=${encodeURIComponent(query)}&auto_search=true`
    }
  }
}

defineExpose({ refresh })
</script>

<style scoped>
.iframe-panel {
  width: 100%;
  height: 100%;
  position: relative;
}
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 12px;
}
.iframe-view {
  width: 100%;
  height: 100%;
  border: none;
}
</style>
