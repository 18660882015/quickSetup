import { ref, watch } from 'vue'

const THEME_KEY = 'mvp-theme'

const theme = ref(localStorage.getItem(THEME_KEY) || 'auto')
const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
  systemDark.value = e.matches
  applyTheme()
})

function isDark() {
  return theme.value === 'dark' || (theme.value === 'auto' && systemDark.value)
}

function applyTheme() {
  document.documentElement.classList.toggle('dark', isDark())
  localStorage.setItem(THEME_KEY, theme.value)
}

export function useTheme() {
  watch(theme, applyTheme, { immediate: true })

  function setTheme(mode) {
    theme.value = mode
  }

  function toggleTheme() {
    theme.value = isDark() ? 'light' : 'dark'
  }

  return { theme, isDark, setTheme, toggleTheme }
}
