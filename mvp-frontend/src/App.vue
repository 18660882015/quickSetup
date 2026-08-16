<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from '@/composables/useI18n'
import AiChat from '@/components/AiChat.vue'
import {
  Odometer,
  Monitor,
  Upload,
  Clock,
  Setting,
  Fold,
  Expand,
  SwitchButton,
  User,
  Sunny,
  Moon,
  Monitor as MonitorIcon,
  ChatDotRound,
  ArrowDown
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { theme, setTheme } = useTheme()
const { locale, setLocale, translate: $t } = useI18n()

const isCollapse = ref(false)
const toggleCollapse = () => {
  isCollapse.value = !isCollapse.value
}

// 登录页不渲染主框架布局
const isLoginPage = computed(() => route.path === '/login')

const menuItems = [
  { index: '/', titleKey: 'menu.dashboard', icon: Odometer },
  { index: '/hosts', titleKey: 'menu.hosts', icon: Monitor },
  { index: '/deploy', titleKey: 'menu.deploy', icon: Upload },
  { index: '/history', titleKey: 'menu.history', icon: Clock },
  { index: '/config', titleKey: 'menu.config', icon: Setting }
]

const activeMenu = computed(() => route.path)

const currentTitle = computed(() => {
  const item = menuItems.find((m) => m.index === route.path)
  return item ? $t(item.titleKey) : $t('app.name')
})

const handleSelect = (index) => {
  if (index !== route.path) {
    router.push(index)
  }
}

const handleCommand = async (command) => {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm($t('app.logoutConfirm'), $t('app.logoutTitle'), {
        confirmButtonText: $t('app.confirm'),
        cancelButtonText: $t('app.cancel'),
        type: 'warning'
      })
      authStore.logout()
      router.push('/login')
    } catch (e) {
      // 用户取消
    }
  }
}

// 主题切换
const themeOptions = computed(() => [
  { value: 'light', label: $t('theme.light'), icon: Sunny },
  { value: 'dark', label: $t('theme.dark'), icon: Moon },
  { value: 'auto', label: $t('theme.auto'), icon: MonitorIcon }
])

// 语言切换
const langOptions = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' }
]

// AI 助手抽屉
const aiChatVisible = ref(false)
</script>

<template>
  <!-- 登录页：全屏渲染，不套用主框架 -->
  <div v-if="isLoginPage" class="login-wrapper">
    <router-view />
  </div>

  <!-- 主框架布局 -->
  <el-container v-else class="app-container">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="app-aside">
      <div class="logo">
        <el-icon class="logo-icon"><Upload /></el-icon>
        <span v-show="!isCollapse" class="logo-text">{{ $t('app.name') }}</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        background-color="#001529"
        text-color="#b7c0cd"
        active-text-color="#ffffff"
        @select="handleSelect"
      >
        <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ $t(item.titleKey) }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-container">
      <el-header class="app-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="toggleCollapse">
            <component :is="isCollapse ? Expand : Fold" />
          </el-icon>
          <span class="header-title">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-dropdown @command="setTheme" trigger="click">
            <span class="theme-trigger">
              <el-icon>
                <component :is="theme === 'dark' ? Moon : theme === 'light' ? Sunny : MonitorIcon" />
              </el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="opt in themeOptions"
                  :key="opt.value"
                  :command="opt.value"
                  :class="{ 'is-active': theme === opt.value }"
                >
                  <el-icon><component :is="opt.icon" /></el-icon>
                  {{ opt.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown @command="setLocale" trigger="click">
            <span class="theme-trigger lang-trigger">
              <span class="lang-label">{{ locale === 'en' ? 'EN' : '中' }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="opt in langOptions"
                  :key="opt.value"
                  :command="opt.value"
                  :class="{ 'is-active': locale === opt.value }"
                >
                  {{ opt.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-tooltip :content="$t('app.aiAssistant')" placement="bottom">
            <el-icon class="header-action-btn" @click="aiChatVisible = true">
              <ChatDotRound />
            </el-icon>
          </el-tooltip>

          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-icon class="user-avatar"><User /></el-icon>
              <span class="username">{{ authStore.user?.username || 'admin' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout" :icon="SwitchButton">
                  {{ $t('app.logout') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>

    <!-- AI 对话助手抽屉 -->
    <AiChat v-model="aiChatVisible" />
  </el-container>
</template>

<style scoped>
.app-container {
  height: 100vh;
  width: 100vw;
}

.app-aside {
  background-color: #001529;
  transition: width 0.28s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  background-color: #002140;
  overflow: hidden;
  white-space: nowrap;
}

.logo-icon {
  font-size: 22px;
  color: #409eff;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
}

.app-aside :deep(.el-menu) {
  border-right: none;
}

.main-container {
  height: 100vh;
  overflow: hidden;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color-light);
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  font-size: 20px;
  cursor: pointer;
  color: var(--el-text-color-primary);
}

.collapse-btn:hover {
  color: #409eff;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 18px;
}

.theme-trigger {
  display: flex;
  align-items: center;
  cursor: pointer;
  font-size: 18px;
  color: var(--el-text-color-primary);
  outline: none;
}

.theme-trigger:hover {
  color: #409eff;
}

.lang-trigger {
  font-size: 12px;
  font-weight: 600;
}

.lang-label {
  padding: 2px 4px;
  border-radius: 4px;
}

.header-action-btn {
  font-size: 18px;
  cursor: pointer;
  color: var(--el-text-color-primary);
}

.header-action-btn:hover {
  color: #409eff;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: var(--el-text-color-primary);
  outline: none;
}

.user-avatar {
  font-size: 18px;
  color: #409eff;
}

.username {
  font-size: 14px;
}

.app-main {
  background-color: var(--el-bg-color-page);
  padding: 20px;
  overflow-y: auto;
}

.login-wrapper {
  height: 100vh;
  width: 100vw;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
