<script setup>
import { ref, computed, onMounted } from 'vue'
import { getHosts } from '@/api/host'

const props = defineProps({
  modelValue: { type: [String, Number, null], default: null },
  filterType: { type: String, default: 'all' }, // local | remote | all
  placeholder: { type: String, default: '请选择主机' },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'change'])

const hosts = ref([])
const loading = ref(false)

const filteredHosts = computed(() => {
  if (props.filterType === 'all') return hosts.value
  if (props.filterType === 'local') return hosts.value.filter((h) => h.is_local)
  // remote
  return hosts.value.filter((h) => !h.is_local)
})

const fetchHosts = async () => {
  loading.value = true
  try {
    const res = await getHosts()
    hosts.value = res.data || []
  } catch (e) {
    // 错误由拦截器统一处理
  } finally {
    loading.value = false
  }
}

const handleChange = (val) => {
  emit('update:modelValue', val)
  const selected = hosts.value.find((h) => h.id === val)
  emit('change', selected || null)
}

const handleVisibleChange = (visible) => {
  if (visible && hosts.value.length === 0) {
    fetchHosts()
  }
}

onMounted(fetchHosts)
</script>

<template>
  <el-select
    :model-value="modelValue"
    :loading="loading"
    :placeholder="placeholder"
    :disabled="disabled"
    filterable
    clearable
    style="width: 100%"
    @change="handleChange"
    @visible-change="handleVisibleChange"
  >
    <el-option
      v-for="host in filteredHosts"
      :key="host.id"
      :label="host.name"
      :value="host.id"
    >
      <div class="host-option">
        <span class="host-name">{{ host.name }}</span>
        <span class="host-meta">{{ host.ip }}:{{ host.port }}</span>
        <el-tag
          :type="host.status === 'online' ? 'success' : 'danger'"
          size="small"
          effect="light"
        >
          {{ host.status === 'online' ? '在线' : '离线' }}
        </el-tag>
      </div>
    </el-option>
    <template #empty>
      <div class="empty-tip">
        <span>暂无可用主机</span>
      </div>
    </template>
  </el-select>
</template>

<style scoped>
.host-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.host-name {
  font-weight: 600;
  color: #303133;
}

.host-meta {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
}

.empty-tip {
  padding: 12px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
</style>
