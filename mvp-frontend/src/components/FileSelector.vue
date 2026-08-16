<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Folder, UploadFilled, Document, Check, Refresh } from '@element-plus/icons-vue'
import { scanProjects, uploadFile } from '@/api/file'

const props = defineProps({
  modelValue: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'change'])

const projects = ref([])
const loading = ref(false)
const uploading = ref(false)

// 预期项目文件类型
const EXPECTED_FILES = ['frontend.zip', 'backend.jar', 'backend.war', 'init.sql', 'project.json']

// 获取项目包含的文件列表
const getProjectFiles = (project) => {
  if (Array.isArray(project.files)) return project.files
  if (Array.isArray(project.file_list)) return project.file_list
  return []
}

// 判断文件是否存在
const hasFile = (project, fileName) => {
  const files = getProjectFiles(project)
  return files.some(
    (f) =>
      f === fileName ||
      f?.name === fileName ||
      (typeof f === 'string' && f.toLowerCase() === fileName.toLowerCase())
  )
}

// 项目卡片是否被选中
const isSelected = (project) => props.modelValue === project.name

const handleSelect = (project) => {
  emit('update:modelValue', project.name)
  emit('change', project)
}

const fetchProjects = async () => {
  loading.value = true
  try {
    const res = await scanProjects()
    projects.value = res.data || []
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    loading.value = false
  }
}

// 上传新项目包
const handleUploadRequest = async (options) => {
  const { file } = options
  // 从文件名推断项目名
  const projectName = file.name.replace(/\.(zip|jar|war|sql|tar\.gz)$/i, '')
  const formData = new FormData()
  formData.append('file', file)
  formData.append('project', projectName)

  uploading.value = true
  try {
    await uploadFile(formData)
    ElMessage.success(`文件「${file.name}」上传成功`)
    await fetchProjects()
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    uploading.value = false
  }
}

const fileTagType = (fileName) => {
  if (fileName.includes('frontend')) return 'primary'
  if (fileName.includes('backend')) return 'success'
  if (fileName.includes('init') || fileName.includes('.sql')) return 'warning'
  if (fileName.includes('project.json')) return 'info'
  return 'info'
}

onMounted(fetchProjects)
</script>

<template>
  <div class="file-selector" v-loading="loading">
    <!-- 操作栏 -->
    <div class="toolbar">
      <el-button :icon="Refresh" size="small" @click="fetchProjects" :loading="loading">
        刷新
      </el-button>
      <el-upload
        :show-file-list="false"
        :http-request="handleUploadRequest"
        :disabled="uploading"
        accept=".zip,.jar,.war,.sql,.tar.gz"
      >
        <el-button type="primary" :icon="UploadFilled" size="small" :loading="uploading">
          上传项目包
        </el-button>
      </el-upload>
    </div>

    <!-- 项目卡片网格 -->
    <div class="project-grid" v-if="projects.length > 0">
      <el-card
        v-for="project in projects"
        :key="project.name"
        shadow="hover"
        class="project-card"
        :class="{ selected: isSelected(project) }"
        @click="handleSelect(project)"
      >
        <div class="card-header">
          <el-icon class="card-icon" :size="20">
            <Folder />
          </el-icon>
          <span class="project-name" :title="project.name">{{ project.name }}</span>
          <el-icon v-if="isSelected(project)" class="check-icon" :size="18" color="#67C23A">
            <Check />
          </el-icon>
        </div>

        <div class="file-tags">
          <template v-for="fileName in EXPECTED_FILES" :key="fileName">
            <el-tag
              v-if="hasFile(project, fileName)"
              :type="fileTagType(fileName)"
              size="small"
              effect="light"
            >
              {{ fileName }}
            </el-tag>
          </template>
          <el-tag
            v-if="getProjectFiles(project).length === 0"
            type="info"
            size="small"
            effect="plain"
          >
            空项目
          </el-tag>
        </div>

        <div class="card-footer" v-if="project.path">
          <el-icon :size="12"><Document /></el-icon>
          <span class="path-text">{{ project.path }}</span>
        </div>
      </el-card>
    </div>

    <!-- 空状态 -->
    <el-empty v-else-if="!loading" description="暂无可用项目，请上传部署包到 deployments 目录">
      <el-upload
        :show-file-list="false"
        :http-request="handleUploadRequest"
        :disabled="uploading"
        accept=".zip,.jar,.war,.sql,.tar.gz"
      >
        <el-button type="primary" :icon="UploadFilled" :loading="uploading">
          上传项目包
        </el-button>
      </el-upload>
    </el-empty>
  </div>
</template>

<style scoped>
.file-selector {
  width: 100%;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.project-card {
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.project-card:hover {
  transform: translateY(-2px);
}

.project-card.selected {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.2);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.card-icon {
  color: #409eff;
  flex-shrink: 0;
}

.project-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.check-icon {
  flex-shrink: 0;
}

.file-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
}

.path-text {
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
