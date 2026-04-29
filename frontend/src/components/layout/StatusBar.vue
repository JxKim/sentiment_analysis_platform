<template>
  <div class="status-bar">
    <div class="status-left">
      <el-tag
        :type="systemStore.connectionStatus === 'connected' ? 'success' : 'danger'"
        size="small"
        effect="dark"
      >
        {{ systemStore.connectionStatus === 'connected' ? '已连接' : '已断开' }}
      </el-tag>
      <span
        v-if="reportStore.currentTask?.status === 'running'"
        class="stream-tag"
      >
        <el-tag
          :type="reportStreamTagType"
          size="small"
          effect="dark"
        >
          {{ reportStreamText }}
        </el-tag>
      </span>
    </div>
    <div class="status-right">
      <span class="clock">{{ currentTime }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSystemStore } from '@/stores/system'
import { useReportStore } from '@/stores/report'

const systemStore = useSystemStore()
const reportStore = useReportStore()

const currentTime = ref('')
let clockTimer: ReturnType<typeof setInterval> | null = null

const reportStreamTagType = computed(() => {
  switch (reportStore.streamStatus) {
    case 'connected': return 'success'
    case 'connecting':
    case 'reconnecting': return 'warning'
    case 'error': return 'danger'
    default: return 'info'
  }
})

const reportStreamText = computed(() => {
  const pct = reportStore.currentTask?.progress || 0
  switch (reportStore.streamStatus) {
    case 'connected': return `报告流 ${pct}%`
    case 'reconnecting': return `报告重连中`
    case 'connecting': return `报告连接中`
    case 'error': return `报告流错误`
    default: return `报告流空闲`
  }
})

function updateClock() {
  currentTime.value = new Date().toLocaleTimeString()
}

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  background: #1a1a2e;
  border-top: 1px solid #333;
  color: #aaa;
  font-size: 12px;
  flex-shrink: 0;
}
.status-left, .status-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.clock {
  font-family: monospace;
  font-size: 13px;
}
</style>
