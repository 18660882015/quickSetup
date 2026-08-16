<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Setting,
  Connection,
  Bell,
  Monitor,
  FolderOpened,
  Check,
  Loading
} from '@element-plus/icons-vue'
import { getConfigs, updateConfig, testAI, testDingtalk } from '@/api/config'
import { formatTime } from '@/utils/format'

// ---- 配置字段定义 ----
// type: string | bool | number ; encrypted: 是否加密存储 ; group: 所属区块
const FIELD_DEFS = [
  // AI 配置
  { key: 'deepseek_api_key', type: 'string', encrypted: true, group: 'ai' },
  { key: 'deepseek_base_url', type: 'string', encrypted: false, group: 'ai' },
  { key: 'deepseek_model', type: 'string', encrypted: false, group: 'ai' },
  // 钉钉配置
  { key: 'dingtalk_webhook', type: 'string', encrypted: true, group: 'dingtalk' },
  { key: 'dingtalk_secret', type: 'string', encrypted: true, group: 'dingtalk' },
  { key: 'dingtalk_enabled', type: 'bool', encrypted: false, group: 'dingtalk' },
  // 监控配置
  { key: 'monitor_time', type: 'string', encrypted: false, group: 'monitor' },
  { key: 'cpu_threshold', type: 'number', encrypted: false, group: 'monitor' },
  { key: 'memory_threshold', type: 'number', encrypted: false, group: 'monitor' },
  { key: 'disk_threshold', type: 'number', encrypted: false, group: 'monitor' },
  // 备份配置
  { key: 'backup_max_count', type: 'number', encrypted: false, group: 'backup' }
]

const AI_GROUP_KEYS = ['deepseek_api_key', 'deepseek_base_url', 'deepseek_model']
const DINGTALK_GROUP_KEYS = ['dingtalk_webhook', 'dingtalk_secret', 'dingtalk_enabled']

// 默认值（与后端种子数据保持一致）
const DEFAULTS = {
  deepseek_api_key: '',
  deepseek_base_url: 'https://api.deepseek.com',
  deepseek_model: 'deepseek-chat',
  dingtalk_webhook: '',
  dingtalk_secret: '',
  dingtalk_enabled: false,
  monitor_time: '02:00',
  cpu_threshold: 80,
  memory_threshold: 80,
  disk_threshold: 90,
  backup_max_count: 5
}

const MODEL_OPTIONS = [
  { label: 'DeepSeek Chat (通用对话)', value: 'deepseek-chat' },
  { label: 'DeepSeek Reasoner (推理模型)', value: 'deepseek-reasoner' }
]

// ---- 表单数据 ----
const form = reactive({ ...DEFAULTS })
// 原始值快照（用于脏值比较）
const originalValues = reactive({ ...DEFAULTS })
// 加密字段是否已配置（后端返回 **** 掩码时为 true）
const encryptedConfigured = reactive({
  deepseek_api_key: false,
  dingtalk_webhook: false,
  dingtalk_secret: false
})
// 配置项描述与更新时间
const configMeta = reactive({})
// 更新时间映射（key -> updated_at）
const updatedAtMap = reactive({})

const loading = ref(false)
const saving = ref(false)
const testingAI = ref(false)
const testingDingtalk = ref(false)

// ---- 类型转换工具 ----
function toFormValue(rawValue, type) {
  if (type === 'bool') {
    return rawValue === 'true' || rawValue === true
  }
  if (type === 'number') {
    const n = Number(rawValue)
    return isNaN(n) ? 0 : n
  }
  return rawValue || ''
}

function toStoreValue(formValue, type) {
  if (type === 'bool') {
    return formValue ? 'true' : 'false'
  }
  if (type === 'number') {
    return String(formValue)
  }
  return formValue
}

// ---- 加载配置 ----
async function loadConfigs() {
  loading.value = true
  try {
    const res = await getConfigs()
    const list = res.data || []
    const mapByKey = {}
    list.forEach((item) => {
      mapByKey[item.config_key] = item
    })

    FIELD_DEFS.forEach((def) => {
      const item = mapByKey[def.key]
      if (!item) {
        // 后端缺失该项时使用默认值
        form[def.key] = DEFAULTS[def.key]
        originalValues[def.key] = DEFAULTS[def.key]
        configMeta[def.key] = def.key
        return
      }
      configMeta[def.key] = item.description || def.key
      if (item.updated_at) updatedAtMap[def.key] = item.updated_at

      if (def.encrypted) {
        // 加密字段：后端返回 **** 表示已配置
        if (item.config_value && item.config_value === '****') {
          encryptedConfigured[def.key] = true
          form[def.key] = ''
          originalValues[def.key] = ''
        } else {
          encryptedConfigured[def.key] = !!item.config_value
          form[def.key] = item.config_value || ''
          originalValues[def.key] = item.config_value || ''
        }
      } else {
        const v = toFormValue(item.config_value, def.type)
        form[def.key] = v
        originalValues[def.key] = v
      }
    })
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    loading.value = false
  }
}

// ---- 收集脏字段并保存 ----
// keys: 要保存的字段 key 列表；返回 { changed, ok, total, failed }
async function saveFields(keys) {
  const updates = []
  keys.forEach((key) => {
    const def = FIELD_DEFS.find((d) => d.key === key)
    if (!def) return
    const cur = form[key]
    if (def.encrypted) {
      // 加密字段：仅在用户输入了非空值时才更新（留空表示不修改）
      if (cur !== undefined && cur !== null && String(cur).trim() !== '') {
        updates.push({ key, value: toStoreValue(cur, def.type), encrypted: true })
      }
    } else {
      if (cur !== originalValues[key]) {
        updates.push({ key, value: toStoreValue(cur, def.type), encrypted: false })
      }
    }
  })

  if (updates.length === 0) {
    return { changed: false, ok: true, total: 0, failed: 0 }
  }

  const results = await Promise.allSettled(
    updates.map((u) =>
      updateConfig(u.key, { config_value: u.value, is_encrypted: u.encrypted })
    )
  )
  const failed = results.filter((r) => r.status === 'rejected').length
  return { changed: true, ok: failed === 0, total: updates.length, failed }
}

// ---- 保存全部配置 ----
async function handleSave() {
  saving.value = true
  try {
    const allKeys = FIELD_DEFS.map((d) => d.key)
    const res = await saveFields(allKeys)
    if (!res.changed) {
      ElMessage.info('没有需要保存的更改')
      return
    }
    if (res.ok) {
      ElMessage.success(`保存成功，共更新 ${res.total} 项配置`)
    } else if (res.failed === res.total) {
      ElMessage.error(`保存失败，${res.failed} 项配置更新失败`)
    } else {
      ElMessage.warning(`部分保存成功：${res.total - res.failed} 项成功，${res.failed} 项失败`)
    }
    await loadConfigs()
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    saving.value = false
  }
}

// ---- 测试 AI 连接 ----
async function handleTestAI() {
  testingAI.value = true
  try {
    // 先保存 AI 相关配置的改动，确保测试使用最新配置
    const saveRes = await saveFields(AI_GROUP_KEYS)
    if (saveRes.changed) {
      if (saveRes.ok) {
        ElMessage.success('AI 配置已保存，正在测试连接...')
      } else {
        ElMessage.warning('部分配置保存失败，将使用已保存的配置测试')
      }
      await loadConfigs()
    }

    if (!encryptedConfigured['deepseek_api_key'] && !form.deepseek_api_key) {
      ElMessage.warning('请先配置 DeepSeek API Key')
      return
    }

    const res = await testAI()
    const data = res.data || {}
    if (data.success) {
      const reply = data.reply ? `：${data.reply}` : ''
      ElMessage.success(data.message ? `${data.message}${reply}` : `AI 连接正常${reply}`)
    } else {
      ElMessage.warning(data.message || 'AI 连接失败，请检查配置')
    }
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    testingAI.value = false
  }
}

// ---- 测试钉钉推送 ----
async function handleTestDingtalk() {
  testingDingtalk.value = true
  try {
    // 先保存钉钉相关配置的改动
    const saveRes = await saveFields(DINGTALK_GROUP_KEYS)
    if (saveRes.changed) {
      if (saveRes.ok) {
        ElMessage.success('钉钉配置已保存，正在测试推送...')
      } else {
        ElMessage.warning('部分配置保存失败，将使用已保存的配置测试')
      }
      await loadConfigs()
    }

    if (!encryptedConfigured['dingtalk_webhook'] && !form.dingtalk_webhook) {
      ElMessage.warning('请先配置钉钉 Webhook URL')
      return
    }

    const res = await testDingtalk()
    const data = res.data || {}
    if (data.success) {
      ElMessage.success(data.message || '钉钉推送测试成功')
    } else {
      ElMessage.warning(data.message || '钉钉推送失败，请检查配置')
    }
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    testingDingtalk.value = false
  }
}

// ---- 辅助：是否已配置加密字段 ----
function encryptedHint(key) {
  return encryptedConfigured[key] ? '已配置，留空表示不修改' : '未配置'
}

function lastUpdated(key) {
  return updatedAtMap[key] ? formatTime(updatedAtMap[key]) : ''
}

onMounted(loadConfigs)
</script>

<template>
  <div class="system-config" v-loading="loading">
    <el-form :model="form" label-width="150px" label-position="right">
      <!-- AI 配置 -->
      <el-card shadow="never" class="config-card">
        <template #header>
          <div class="card-header">
            <el-icon class="header-icon" color="#409eff"><Connection /></el-icon>
            <span>AI 配置</span>
            <el-tag size="small" type="primary" effect="plain">DeepSeek</el-tag>
          </div>
        </template>

        <el-form-item label="API Key">
          <el-input
            v-model="form.deepseek_api_key"
            type="password"
            show-password
            placeholder="请输入 DeepSeek API Key"
            clearable
          />
          <div class="field-hint">
            <el-tag size="small" :type="encryptedConfigured.deepseek_api_key ? 'success' : 'info'">
              {{ encryptedHint('deepseek_api_key') }}
            </el-tag>
            <span v-if="lastUpdated('deepseek_api_key')" class="updated-time">
              最近更新：{{ lastUpdated('deepseek_api_key') }}
            </span>
          </div>
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input
            v-model="form.deepseek_base_url"
            placeholder="https://api.deepseek.com"
            clearable
          />
        </el-form-item>

        <el-form-item label="模型选择">
          <el-select v-model="form.deepseek_model" placeholder="请选择模型" style="width: 100%">
            <el-option
              v-for="opt in MODEL_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="操作">
          <el-button
            type="primary"
            :icon="testingAI ? Loading : Connection"
            :loading="testingAI"
            @click="handleTestAI"
          >
            测试 AI 连接
          </el-button>
        </el-form-item>
      </el-card>

      <!-- 钉钉配置 -->
      <el-card shadow="never" class="config-card">
        <template #header>
          <div class="card-header">
            <el-icon class="header-icon" color="#e6a23c"><Bell /></el-icon>
            <span>钉钉通知配置</span>
          </div>
        </template>

        <el-form-item label="Webhook URL">
          <el-input
            v-model="form.dingtalk_webhook"
            type="password"
            show-password
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxx"
            clearable
          />
          <div class="field-hint">
            <el-tag size="small" :type="encryptedConfigured.dingtalk_webhook ? 'success' : 'info'">
              {{ encryptedHint('dingtalk_webhook') }}
            </el-tag>
          </div>
        </el-form-item>

        <el-form-item label="签名秘钥">
          <el-input
            v-model="form.dingtalk_secret"
            type="password"
            show-password
            placeholder="SEC 开头的签名秘钥（可选）"
            clearable
          />
          <div class="field-hint">
            <el-tag size="small" :type="encryptedConfigured.dingtalk_secret ? 'success' : 'info'">
              {{ encryptedHint('dingtalk_secret') }}
            </el-tag>
          </div>
        </el-form-item>

        <el-form-item label="启用通知">
          <el-switch
            v-model="form.dingtalk_enabled"
            active-text="启用"
            inactive-text="停用"
          />
        </el-form-item>

        <el-form-item label="操作">
          <el-button
            type="primary"
            :icon="testingDingtalk ? Loading : Bell"
            :loading="testingDingtalk"
            @click="handleTestDingtalk"
          >
            测试推送
          </el-button>
        </el-form-item>
      </el-card>

      <!-- 监控配置 -->
      <el-card shadow="never" class="config-card">
        <template #header>
          <div class="card-header">
            <el-icon class="header-icon" color="#67c23a"><Monitor /></el-icon>
            <span>监控配置</span>
          </div>
        </template>

        <el-form-item label="每日检查时间">
          <el-time-picker
            v-model="form.monitor_time"
            value-format="HH:mm"
            format="HH:mm"
            placeholder="选择时间"
            style="width: 200px"
          />
          <span class="inline-hint">每日定时生成监控报告并推送</span>
        </el-form-item>

        <el-form-item label="CPU 告警阈值">
          <div class="slider-row">
            <el-slider
              v-model="form.cpu_threshold"
              :min="0"
              :max="100"
              :step="1"
              show-input
              :show-input-controls="false"
              input-size="small"
              style="max-width: 520px"
            />
            <span class="slider-unit">%</span>
          </div>
        </el-form-item>

        <el-form-item label="内存告警阈值">
          <div class="slider-row">
            <el-slider
              v-model="form.memory_threshold"
              :min="0"
              :max="100"
              :step="1"
              show-input
              :show-input-controls="false"
              input-size="small"
              style="max-width: 520px"
            />
            <span class="slider-unit">%</span>
          </div>
        </el-form-item>

        <el-form-item label="磁盘告警阈值">
          <div class="slider-row">
            <el-slider
              v-model="form.disk_threshold"
              :min="0"
              :max="100"
              :step="1"
              show-input
              :show-input-controls="false"
              input-size="small"
              style="max-width: 520px"
            />
            <span class="slider-unit">%</span>
          </div>
        </el-form-item>
      </el-card>

      <!-- 备份配置 -->
      <el-card shadow="never" class="config-card">
        <template #header>
          <div class="card-header">
            <el-icon class="header-icon" color="#909399"><FolderOpened /></el-icon>
            <span>备份配置</span>
          </div>
        </template>

        <el-form-item label="最大保留备份数">
          <el-input-number
            v-model="form.backup_max_count"
            :min="1"
            :max="100"
            :step="1"
            controls-position="right"
          />
          <span class="inline-hint">超出数量自动清理最早的备份</span>
        </el-form-item>
      </el-card>

      <!-- 保存按钮 -->
      <div class="save-bar">
        <el-button
          type="primary"
          size="large"
          :icon="Check"
          :loading="saving"
          @click="handleSave"
        >
          保存配置
        </el-button>
        <el-button size="large" :icon="Setting" @click="loadConfigs">重置</el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped>
.system-config {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.config-card {
  border-radius: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.header-icon {
  font-size: 18px;
}

.field-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

.updated-time {
  color: #909399;
}

.inline-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.slider-unit {
  color: #909399;
  font-size: 13px;
}

.save-bar {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 0;
}

/* 调整 slider 内嵌 input 宽度 */
:deep(.el-slider__input) {
  width: 64px;
}
</style>
