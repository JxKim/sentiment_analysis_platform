<template>
  <div class="forum-chat" ref="chatRef">
    <div v-if="forumStore.messages.length === 0" class="forum-empty">
      <el-icon :size="36"><ChatDotRound /></el-icon>
      <p>Forum Engine 未启动或暂无消息</p>
    </div>
    <div
      v-for="msg in forumStore.messages"
      :key="msg.id"
      class="forum-message"
      :class="`msg-${msg.type}`"
    >
      <span class="msg-agent">{{ msg.agent }}</span>
      <span class="msg-time">{{ msg.timestamp }}</span>
      <div class="msg-content">{{ msg.content }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch, ref, nextTick } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'
import { useForumStore } from '@/stores/forum'

const forumStore = useForumStore()
const chatRef = ref<HTMLElement | null>(null)

watch(
  () => forumStore.messages.length,
  async () => {
    await nextTick()
    if (chatRef.value) {
      chatRef.value.scrollTop = chatRef.value.scrollHeight
    }
  },
)
</script>

<style scoped>
.forum-chat {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: #fafafa;
}
.forum-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 8px;
}
.forum-message {
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.forum-message.msg-user {
  border-left: 3px solid #409eff;
}
.forum-message.msg-agent {
  border-left: 3px solid #67c23a;
}
.forum-message.msg-system {
  border-left: 3px solid #e6a23c;
  background: #fef9e7;
}
.forum-message.msg-host {
  border-left: 3px solid #909399;
}
.msg-agent {
  font-weight: 600;
  font-size: 12px;
  color: #303133;
}
.msg-time {
  font-size: 11px;
  color: #909399;
  margin-left: 8px;
}
.msg-content {
  margin-top: 4px;
  font-size: 13px;
  white-space: pre-wrap;
  line-height: 1.5;
}
</style>
