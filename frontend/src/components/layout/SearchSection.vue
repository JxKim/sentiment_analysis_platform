<template>
  <div class="search-section">
    <div class="search-bar">
      <el-input
        v-model="query"
        placeholder="输入搜索关键词，然后点击「开始」"
        size="large"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #append>
          <el-button
            type="primary"
            :loading="searchStore.searching"
            @click="handleSearch"
          >
            开始
          </el-button>
        </template>
      </el-input>
    </div>
    <div class="search-actions">
      <label class="template-upload">
        <input
          type="file"
          accept=".md,.txt"
          style="display:none"
          @change="handleFileUpload"
        />
        <el-button size="small" tag="span">
          <el-icon><Upload /></el-icon>
          上传自定义模板
        </el-button>
      </label>
      <el-button
        size="small"
        :icon="Setting"
        @click="configStore.openModal"
      >
        LLM 配置
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Upload, Setting } from '@element-plus/icons-vue'
import { useSearchStore } from '@/stores/search'
import { useConfigStore } from '@/stores/config'

const searchStore = useSearchStore()
const configStore = useConfigStore()

const query = ref('')

function handleSearch() {
  if (query.value.trim()) {
    searchStore.performSearch(query.value.trim())
  }
}

function handleFileUpload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file && file.size <= 1024 * 1024) {
    const reader = new FileReader()
    reader.onload = (ev) => {
      const content = ev.target?.result as string
      configStore.values.custom_template = content
    }
    reader.readAsText(file)
  }
}
</script>

<style scoped>
.search-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  background: #f0f2f5;
  border-bottom: 1px solid #dcdfe6;
}
.search-bar {
  flex: 1;
}
.search-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
</style>
