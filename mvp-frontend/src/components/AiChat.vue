<script setup>
import { ref, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Delete, Loading } from '@element-plus/icons-vue'
import request from '@/api'

const visible = defineModel({ type: Boolean, default: false })

const messages = ref([
  {
    role: 'assistant',
    content: '你好！我是 AI 运维助手。可以问我部署排错、配置优化（JVM/Nginx/MySQL）、脚本编写等问题。我会自动获取你最近的部署记录和主机状态作为上下文。',
    time: new Date().toLocaleTimeString()
  }
])
const userInput = ref('')
const loading = ref(false)
const bodyRef = ref(null)

const quickQuestions = [
  '帮我分析最近的部署失败原因',
  '推荐一个 4核16G 服务器的 JVM 参数',
  '写一个 Nginx 静态资源缓存配置',
  'MySQL 连接数不够怎么优化？'
]

async function send(text) {
  const content = (text || userInput.value).trim()
  if (!content || loading.value) return

  messages.value.push({ role: 'user', content, time: new Date().toLocaleTimeString() })
  userInput.value = ''
  loading.value = true
  scrollToBottom()

  try {
    const res = await request.post('/ai/chat', {
      messages: messages.value
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content })),
      with_context: true
    })
    const reply = res.data?.reply || 'AI 未返回内容'
    messages.value.push({ role: 'assistant', content: reply, time: new Date().toLocaleTimeString() })
  } catch (e) {
    messages.value.push({
      role: 'assistant',
      content: `AI 调用失败: ${e.response?.data?.msg || e.message}`,
      time: new Date().toLocaleTimeString()
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function clearChat() {
  messages.value = [
    {
      role: 'assistant',
      content: '对话已清空，有什么可以帮你？',
      time: new Date().toLocaleTimeString()
    }
  ]
}

function scrollToBottom() {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onUnmounted(() => {})
</script>

<template>
  <el-drawer
    v-model="visible"
    title="AI 运维助手"
    direction="rtl"
    size="440px"
    :append-to-body="true"
  >
    <div class="ai-chat">
      <!-- 消息列表 -->
      <div ref="bodyRef" class="chat-body">
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="msg-row"
          :class="msg.role === 'user' ? 'msg-user' : 'msg-ai'"
        >
          <div class="msg-bubble">
            <div class="msg-content">{{ msg.content }}</div>
            <div class="msg-time">{{ msg.time }}</div>
          </div>
        </div>
        <div v-if="loading" class="msg-row msg-ai">
          <div class="msg-bubble typing">
            <el-icon class="is-loading"><Loading /></el-icon>
            AI 正在思考...
          </div>
        </div>
      </div>

      <!-- 快捷提问 -->
      <div class="quick-questions" v-if="messages.length <= 2">
        <el-tag
          v-for="q in quickQuestions"
          :key="q"
          class="quick-tag"
          effect="plain"
          @click="send(q)"
        >
          {{ q }}
        </el-tag>
      </div>

      <!-- 输入区 -->
      <div class="chat-input">
        <el-input
          v-model="userInput"
          type="textarea"
          :rows="2"
          placeholder="输入问题，Enter 发送"
          @keydown.enter.exact.prevent="send()"
          :disabled="loading"
        />
        <div class="input-actions">
          <el-button size="small" :icon="Delete" @click="clearChat" text>清空</el-button>
          <el-button
            size="small"
            type="primary"
            :icon="Promotion"
            :loading="loading"
            @click="send()"
          >
            发送
          </el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.ai-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px;
}

.msg-row {
  display: flex;
  margin-bottom: 12px;
}

.msg-user {
  justify-content: flex-end;
}

.msg-bubble {
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.msg-ai .msg-bubble {
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  border-top-left-radius: 2px;
}

.msg-user .msg-bubble {
  background-color: #409eff;
  color: #fff;
  border-top-right-radius: 2px;
}

.msg-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-time {
  font-size: 11px;
  opacity: 0.6;
  margin-top: 4px;
  text-align: right;
}

.typing {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
}

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 0;
}

.quick-tag {
  cursor: pointer;
}

.quick-tag:hover {
  color: #409eff;
  border-color: #409eff;
}

.chat-input {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 10px;
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
</style>
