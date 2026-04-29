<template>
  <div class="console-output" ref="consoleRef">
    <div v-if="lines.length === 0" class="console-empty">
      暂无日志输出
    </div>
    <div
      v-for="(line, idx) in lines"
      :key="idx"
      class="console-line"
    >
      {{ line }}
    </div>
    <div v-if="lines.length > 100" class="console-actions">
      <el-button size="small" text @click="clearLog">清空日志</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useAppsStore } from '@/stores/apps'

const appsStore = useAppsStore()
const consoleRef = ref<HTMLElement | null>(null)

const lines = computed(() => {
  const app = appsStore.activeApp
  return appsStore.logBuffers[app] || []
})

function clearLog() {
  const app = appsStore.activeApp
  appsStore.clearLogBuffer(app)
}

// Auto-scroll to bottom on new lines
watch(
  () => lines.value.length,
  async () => {
    await nextTick()
    if (consoleRef.value) {
      consoleRef.value.scrollTop = consoleRef.value.scrollHeight
    }
  },
)
</script>

<style scoped>
.console-output {
  flex: 1;
  overflow-y: auto;
  background: #0c0c1d;
  color: #0f0;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  padding: 8px;
  white-space: pre-wrap;
  word-break: break-all;
  position: relative;
}
.console-empty {
  color: #555;
  padding: 20px;
  text-align: center;
}
.console-line {
  min-height: 18px;
  line-height: 1.4;
}
.console-actions {
  position: sticky;
  bottom: 4px;
  text-align: center;
}
</style>
