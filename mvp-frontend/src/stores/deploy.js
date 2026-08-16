import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useDeployStore = defineStore('deploy', () => {
  // 部署状态：idle | planning | executing | success | failed | cancelled
  const deployStatus = ref('idle')
  // 当前部署任务信息
  const currentTask = ref(null)
  // AI 生成的部署计划
  const plan = ref(null)
  // 实时日志缓冲
  const logs = ref([])

  function setStatus(status) {
    deployStatus.value = status
  }

  function setTask(task) {
    currentTask.value = task
  }

  function setPlan(p) {
    plan.value = p
  }

  function appendLog(log) {
    logs.value.push(log)
  }

  function clearLogs() {
    logs.value = []
  }

  // 重置全部部署状态
  function reset() {
    deployStatus.value = 'idle'
    currentTask.value = null
    plan.value = null
    logs.value = []
  }

  return {
    deployStatus,
    currentTask,
    plan,
    logs,
    setStatus,
    setTask,
    setPlan,
    appendLog,
    clearLogs,
    reset
  }
})
