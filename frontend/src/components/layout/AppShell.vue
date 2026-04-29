<template>
  <el-container class="app-shell">
    <el-header height="auto" class="app-header">
      <TheHeader />
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
</script>

<style scoped>
.app-shell {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}
.app-header {
  flex-shrink: 0;
  background: #fff;
  border-bottom: 2px solid #1a1a2e;
  padding: 0;
}
.app-main {
  flex: 1;
  overflow: hidden;
}
.embedded-section {
  flex: 1.8;
  overflow: hidden;
  padding: 0;
  position: relative;
}
.console-section {
  flex: 1.2;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 2px solid #1a1a2e;
  background: var(--el-bg-color-page);
}
</style>
