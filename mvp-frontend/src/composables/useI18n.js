import { ref, computed } from 'vue'

/**
 * 轻量中英双语支持（基础版）
 * 覆盖应用外壳（菜单/头部/通用操作），页面内部文案保持中文。
 */
const messages = {
  zh: {
    app: {
      name: 'AI部署助手',
      aiAssistant: 'AI 助手',
      logout: '退出登录',
      logoutConfirm: '确定要退出登录吗？',
      logoutTitle: '提示',
      confirm: '确定',
      cancel: '取消'
    },
    menu: {
      dashboard: 'Dashboard',
      hosts: '主机管理',
      deploy: '部署向导',
      history: '部署历史',
      config: '系统配置'
    },
    theme: {
      label: '主题',
      light: '亮色',
      dark: '暗色',
      auto: '跟随系统'
    },
    lang: {
      label: '语言',
      zh: '中文',
      en: 'English'
    }
  },
  en: {
    app: {
      name: 'AI Deploy',
      aiAssistant: 'AI Assistant',
      logout: 'Logout',
      logoutConfirm: 'Are you sure you want to log out?',
      logoutTitle: 'Notice',
      confirm: 'OK',
      cancel: 'Cancel'
    },
    menu: {
      dashboard: 'Dashboard',
      hosts: 'Hosts',
      deploy: 'Deploy',
      history: 'History',
      config: 'Settings'
    },
    theme: {
      label: 'Theme',
      light: 'Light',
      dark: 'Dark',
      auto: 'System'
    },
    lang: {
      label: 'Language',
      zh: '中文',
      en: 'English'
    }
  }
}

const locale = ref(localStorage.getItem('locale') || 'zh')

export function useI18n() {
  const t = computed(() => messages[locale.value] || messages.zh)

  const translate = (path) => {
    const parts = path.split('.')
    let value = t.value
    for (const part of parts) {
      if (value == null) return path
      value = value[part]
    }
    return value ?? path
  }

  const setLocale = (lang) => {
    locale.value = lang
    localStorage.setItem('locale', lang)
    document.documentElement.setAttribute('lang', lang === 'en' ? 'en' : 'zh-CN')
  }

  return { locale, t, translate, setLocale }
}
