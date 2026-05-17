<template>
  <el-container class="app-shell">
    <el-header height="auto" class="app-header">
      <TheHeader @refresh="$emit('refresh')" />
      <SearchSection />
    </el-header>
    <el-container class="app-main">
      <el-main class="embedded-section">
        <slot name="content" />
      </el-main>
      <el-aside width="35%" class="console-section">
        <AppSwitcher />
        <ConsoleOutput />
      </el-aside>
    </el-container>
    <StatusBar />
  </el-container>
</template>

<script setup lang="ts">
import TheHeader from './TheHeader.vue'
import SearchSection from './SearchSection.vue'
import AppSwitcher from './AppSwitcher.vue'
import ConsoleOutput from '../console/ConsoleOutput.vue'
import StatusBar from './StatusBar.vue'

defineEmits<{
  refresh: []
}>()
</script>

<style scoped>
.app-shell {
  height: 100vh;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  border: 2px solid #1a1a2e;
}
.app-header {
  flex-shrink: 0;
  background: #fff;
  padding: 0;
}
.app-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.embedded-section {
  flex: 1.8;
  min-height: 0;
  overflow: hidden;
  padding: 0;
  position: relative;
}
.console-section {
  flex: 1.2;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 3px solid #1a1a2e;
  background: var(--el-bg-color-page);
}
</style>
