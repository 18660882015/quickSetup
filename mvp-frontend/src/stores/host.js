import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getHosts } from '@/api/host'

export const useHostStore = defineStore('host', () => {
  const hosts = ref([])
  const currentHost = ref(null)
  const loading = ref(false)

  // 拉取主机列表
  async function fetchHosts() {
    loading.value = true
    try {
      const res = await getHosts()
      hosts.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  // 设置当前选中的主机
  function setCurrentHost(host) {
    currentHost.value = host
  }

  // 按 id 清除单台主机缓存（删除/更新后调用）
  function removeHost(id) {
    hosts.value = hosts.value.filter((h) => h.id !== id)
    if (currentHost.value?.id === id) {
      currentHost.value = null
    }
  }

  // 新增主机后追加到列表
  function addHost(host) {
    hosts.value.unshift(host)
  }

  // 更新列表中的主机信息
  function updateHostInList(host) {
    const idx = hosts.value.findIndex((h) => h.id === host.id)
    if (idx !== -1) {
      hosts.value[idx] = { ...hosts.value[idx], ...host }
    }
  }

  return {
    hosts,
    currentHost,
    loading,
    fetchHosts,
    setCurrentHost,
    removeHost,
    addHost,
    updateHostInList
  }
})
