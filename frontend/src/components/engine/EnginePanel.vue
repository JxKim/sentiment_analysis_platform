<template>
  <div class="engine-panel">
    <!-- Idle state: no search yet -->
    <div v-if="state.status === 'idle'" class="placeholder">
      <el-icon :size="48"><Search /></el-icon>
      <p>{{ engineLabel }} 等待查询</p>
      <p class="hint">从上方搜索框输入内容后按回车</p>
    </div>

    <!-- Running state: progress -->
    <div v-else-if="state.status === 'running'" class="progress-area">
      <el-progress
        :percentage="state.progressPct"
        :stroke-width="20"
        :text-inside="true"
        :status="state.progressPct === 100 ? 'success' : undefined"
      />
      <p class="status-msg">{{ state.message }}</p>
      <p v-if="state.paragraphTotal > 0" class="para-info">
        段落 {{ state.paragraphCurrent }} / {{ state.paragraphTotal }}
      </p>
    </div>

    <!-- Error state -->
    <div v-else-if="state.status === 'error'" class="error-area">
      <el-alert :title="state.error" type="error" show-icon :closable="false" />
    </div>

    <!-- Done: show results -->
    <div v-else-if="state.status === 'done'" class="results-area">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="研究小结" name="summary">
          <div class="markdown-body" v-html="renderedReport" />
        </el-tab-pane>
        <el-tab-pane label="引用信息" name="citations">
          <div v-if="state.citations.length === 0" class="empty-citations">
            暂无引用信息
          </div>
          <el-collapse v-else>
            <el-collapse-item
              v-for="(citation, idx) in state.citations"
              :key="idx"
              :title="`搜索 ${idx + 1}: ${citation.query || '未记录查询'}`"
            >
              <p><strong>段落:</strong> {{ citation.paragraph_title }}</p>
              <p><strong>URL:</strong> {{ citation.url || '无' }}</p>
              <p><strong>标题:</strong> {{ citation.title || '无' }}</p>
              <p><strong>内容预览:</strong> {{ citation.content || '无可用内容' }}</p>
              <p v-if="citation.score"><strong>相关度评分:</strong> {{ citation.score }}</p>
              <p><strong>搜索次数:</strong> {{ citation.search_count }}</p>
              <p><strong>反思次数:</strong> {{ citation.reflection_count }}</p>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { useSearchStore, type EngineState } from '@/stores/search'

const props = withDefaults(defineProps<{
  engine: 'insight' | 'media' | 'query'
}>(), {})

const engineLabel = computed(() => {
  const labels: Record<string, string> = { insight: 'Insight Agent', media: 'Media Agent', query: 'Query Agent' }
  return labels[props.engine] || props.engine
})

const activeTab = ref('summary')

const searchStore = useSearchStore()
const state = computed<EngineState>(() => searchStore.engines[props.engine])

const renderedReport = computed(() => {
  if (!state.value.finalReport) return ''
  return marked(state.value.finalReport) as string
})

// Reset tab when state changes to running (new search started)
watch(() => state.value.status, (newStatus) => {
  if (newStatus === 'running') {
    activeTab.value = 'summary'
  }
})
</script>

<style scoped>
.engine-panel {
  width: 100%;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
}

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 8px;
}
.placeholder .hint {
  font-size: 12px;
  color: #c0c4cc;
}

.progress-area {
  padding: 40px 20px;
  text-align: center;
}
.status-msg {
  margin-top: 16px;
  color: #606266;
}
.para-info {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.error-area {
  padding: 40px 20px;
}

.results-area {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.results-area :deep(.el-tabs) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.results-area :deep(.el-tabs__header) {
  flex-shrink: 0;
}
.results-area :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 32px;
  box-sizing: border-box;
}
.results-area :deep(.el-tab-pane) {
  min-height: 100%;
}

.markdown-body {
  padding: 8px 0 48px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) {
  margin-top: 1em;
  margin-bottom: 0.5em;
}
.markdown-body :deep(p) {
  margin: 0.5em 0;
}
.markdown-body :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}
.markdown-body :deep(pre) {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.markdown-body :deep(blockquote) {
  border-left: 4px solid #409eff;
  margin: 0.5em 0;
  padding: 4px 12px;
  color: #606266;
  background: #f0f5ff;
}

.empty-citations {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}
</style>
