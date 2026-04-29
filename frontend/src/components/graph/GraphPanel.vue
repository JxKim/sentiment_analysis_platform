<template>
  <div class="graph-panel" :class="{ collapsed }">
    <div class="graph-header" @click="collapsed = !collapsed">
      <span class="graph-title">
        <el-icon><Connection /></el-icon> 知识图谱
      </span>
      <el-icon><ArrowDown v-if="!collapsed" /><ArrowRight v-else /></el-icon>
    </div>
    <div v-show="!collapsed" class="graph-body">
      <div v-if="graphStore.state === 'loading'" class="graph-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <div v-else-if="graphStore.state === 'error'" class="graph-error">
        图谱加载失败
      </div>
      <div v-else-if="graphStore.state === 'idle'" class="graph-empty">
        暂无图谱数据
      </div>
      <VisNetworkGraph
        v-else
        :nodes="graphStore.nodes"
        :edges="graphStore.edges"
        height="360px"
        @node-click="onNodeClick"
        @node-deselect="onNodeDeselect"
      />
      <div v-if="graphStore.selectedNode" class="node-detail">
        <h5>{{ graphStore.selectedNode.label }}</h5>
        <p v-if="graphStore.selectedNode.group">类型: {{ graphStore.selectedNode.group }}</p>
        <el-button size="small" text @click="graphStore.selectNode(null)">关闭</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Connection, ArrowDown, ArrowRight, Loading } from '@element-plus/icons-vue'
import { useGraphStore } from '@/stores/graph'
import VisNetworkGraph from './VisNetworkGraph.vue'

const graphStore = useGraphStore()
const collapsed = ref(false)

function onNodeClick(_nodeId: string, node: any) {
  graphStore.selectNode(node)
}

function onNodeDeselect() {
  graphStore.selectNode(null)
}
</script>

<style scoped>
.graph-panel {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  margin-top: 8px;
  overflow: hidden;
}
.graph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f5f7fa;
  cursor: pointer;
  user-select: none;
}
.graph-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
}
.graph-body {
  padding: 8px;
}
.graph-loading, .graph-error, .graph-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  color: #909399;
  font-size: 13px;
}
.collapsed .graph-body {
  display: none;
}
.node-detail {
  padding: 8px 12px;
  background: #f0f9eb;
  border-radius: 4px;
  margin-top: 6px;
  font-size: 12px;
}
.node-detail h5 {
  margin: 0 0 4px;
  font-size: 13px;
}
</style>
