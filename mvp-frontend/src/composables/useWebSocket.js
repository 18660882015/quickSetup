import { ref, onUnmounted } from 'vue'

/**
 * WebSocket 封装 Composable
 *
 * 特性：
 * - 自动连接、断线重连（默认最多 3 次，间隔 3 秒）
 * - 心跳检测（默认 30 秒 ping/pong）
 * - 消息自动 JSON 解析为响应式数据
 * - 组件卸载时自动关闭连接
 *
 * @param {string} url WebSocket 连接地址
 * @param {object} options 配置项
 * @param {boolean} [options.autoConnect=true] 是否自动连接
 * @param {number} [options.maxRetries=3] 断线重连最大次数
 * @param {number} [options.retryInterval=3000] 重连间隔（毫秒）
 * @param {number} [options.heartbeatInterval=30000] 心跳间隔（毫秒）
 * @param {function} [options.onMessage] 消息回调
 * @param {function} [options.onOpen] 连接成功回调
 * @param {function} [options.onClose] 连接关闭回调
 * @param {function} [options.onError] 连接错误回调
 * @returns {{ data: import('vue').Ref, status: import('vue').Ref<string>, messages: import('vue').Ref<Array>, send: Function, connect: Function, close: Function, reconnect: Function }}
 */
export function useWebSocket(url, options = {}) {
  const {
    autoConnect = true,
    maxRetries = 3,
    retryInterval = 3000,
    heartbeatInterval = 30000,
    onMessage,
    onOpen,
    onClose,
    onError
  } = options

  // 响应式状态
  const data = ref(null) // 最新一条消息
  const status = ref('idle') // idle | connecting | connected | reconnecting | closed | error
  const messages = ref([]) // 全部消息（不含 ping/pong）

  // 内部变量
  let currentUrl = url
  let ws = null
  let retryCount = 0
  let heartbeatTimer = null
  let reconnectTimer = null
  let closedByUser = false

  /** 启动心跳定时器 */
  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: 'ping' }))
        } catch (e) {
          // 发送失败忽略，由 onclose 处理重连
        }
      }
    }, heartbeatInterval)
  }

  /** 停止心跳定时器 */
  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  /** 清除重连定时器 */
  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  /** 移除当前 ws 实例的事件监听 */
  function detachWs() {
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
    }
  }

  /** 调度断线重连 */
  function scheduleReconnect() {
    if (closedByUser) return
    if (retryCount >= maxRetries) {
      status.value = 'error'
      return
    }
    retryCount++
    status.value = 'reconnecting'
    reconnectTimer = setTimeout(() => {
      connect()
    }, retryInterval)
  }

  /** 建立连接 */
  function connect(connectUrl) {
    // 若传入新 URL 则更新
    if (connectUrl) currentUrl = connectUrl
    if (!currentUrl) return

    // 先清理旧连接（不触发重连）
    detachWs()
    if (ws) {
      try {
        ws.close()
      } catch (e) {
        // 忽略
      }
      ws = null
    }
    stopHeartbeat()
    clearReconnectTimer()

    closedByUser = false
    status.value = 'connecting'

    try {
      ws = new WebSocket(currentUrl)
    } catch (e) {
      status.value = 'error'
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      retryCount = 0
      status.value = 'connected'
      startHeartbeat()
      if (typeof onOpen === 'function') onOpen()
    }

    ws.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch (e) {
        payload = { type: 'raw', message: event.data }
      }

      // 忽略心跳响应
      if (payload.type === 'pong') return

      data.value = payload
      messages.value.push(payload)

      if (typeof onMessage === 'function') onMessage(payload)
    }

    ws.onerror = (e) => {
      status.value = 'error'
      if (typeof onError === 'function') onError(e)
    }

    ws.onclose = () => {
      stopHeartbeat()
      if (closedByUser) {
        status.value = 'closed'
        return
      }
      status.value = 'closed'
      if (typeof onClose === 'function') onClose()
      // 断线重连
      scheduleReconnect()
    }
  }

  /** 主动发送消息 */
  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
      return true
    }
    return false
  }

  /** 关闭连接（不触发重连） */
  function close() {
    closedByUser = true
    stopHeartbeat()
    clearReconnectTimer()
    detachWs()
    if (ws) {
      try {
        ws.close()
      } catch (e) {
        // 忽略
      }
      ws = null
    }
    status.value = 'closed'
  }

  /** 重置重连计数并重新连接 */
  function reconnect() {
    retryCount = 0
    closedByUser = false
    connect()
  }

  if (autoConnect && currentUrl) {
    connect()
  }

  // 组件卸载时自动关闭
  onUnmounted(() => {
    close()
  })

  return {
    data,
    status,
    messages,
    send,
    connect,
    close,
    reconnect
  }
}
