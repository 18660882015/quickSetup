import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, getMe } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  const isLoggedIn = computed(() => !!token.value)

  // 登录
  async function login(username, password) {
    const res = await loginApi({ username, password })
    const data = res.data || {}
    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
    user.value = { username: data.username || username, role: data.role || 'admin' }
    localStorage.setItem('user', JSON.stringify(user.value))
    return res
  }

  // 拉取当前用户信息
  async function fetchUser() {
    if (!token.value) return
    try {
      const res = await getMe()
      user.value = res.data || user.value
      localStorage.setItem('user', JSON.stringify(user.value))
    } catch (e) {
      // 忽略，由拦截器处理
    }
  }

  // 退出登录
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return { token, user, isLoggedIn, login, fetchUser, logout }
})
