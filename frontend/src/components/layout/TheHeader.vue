<template>
  <div class="the-header">
    <div class="header-left">
      <el-image
        src="/static/image/logo_compressed.png"
        alt="Logo"
        class="logo"
        fit="contain"
      />
      <h1 class="title">尚舆分析平台 - Atguigu SentinelAI</h1>
    </div>
    <div class="header-right">
      <el-button
        :icon="Refresh"
        circle
        @click="$emit('refresh')"
        title="刷新状态"
      />
      <el-button
        type="danger"
        :icon="SwitchButton"
        circle
        @click="$emit('shutdown')"
        title="系统关机"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { Refresh, SwitchButton } from '@element-plus/icons-vue'

defineEmits<{
  refresh: []
  shutdown: []
}>()
</script>

<style scoped>
.the-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px;
  background: #1a1a2e;
  color: #fff;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo {
  width: 40px;
  height: 40px;
}
.title {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}
.header-right {
  display: flex;
  gap: 8px;
}
</style>
