<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <div class="code">404</div>
    <h1>页面不存在</h1>
    <p>你访问的页面可能已被移除，或链接有误。</p>
    <el-button type="primary" @click="router.push({ name: 'chat' })">返回智能问答</el-button>
  </div>
</template>

<style scoped>
.not-found {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-2);
}

.code {
  font-size: 72px;
  font-weight: 800;
  color: var(--primary);
  line-height: 1;
}

.not-found h1 {
  margin: 6px 0 0;
  font-size: 20px;
  color: var(--text-1);
}

.not-found p {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--text-3);
}
</style>
