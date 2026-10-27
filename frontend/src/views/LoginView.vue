<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mode = ref('login') // login | register
const loading = ref(false)
const error = ref('')

const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({
  username: '',
  password: '',
  confirm: '',
  real_name: '',
  email: '',
  invite_code: '',
})

function goNext() {
  router.push(route.query.redirect ? String(route.query.redirect) : { name: 'chat' })
}

async function submitLogin() {
  error.value = ''
  if (!loginForm.username || !loginForm.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    goNext()
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  error.value = ''
  if (regForm.username.length < 4) return (error.value = '用户名至少 4 位')
  if (regForm.password.length < 8 || !/[a-zA-Z]/.test(regForm.password) || !/\d/.test(regForm.password))
    return (error.value = '密码需 8~32 位且同时包含字母与数字')
  if (regForm.password !== regForm.confirm) return (error.value = '两次输入的密码不一致')
  loading.value = true
  try {
    await auth.register({
      username: regForm.username,
      password: regForm.password,
      real_name: regForm.real_name || undefined,
      email: regForm.email || undefined,
      invite_code: regForm.invite_code || undefined,
    })
    // 注册成功后自动登录
    await auth.login(regForm.username, regForm.password)
    goNext()
  } catch (e) {
    error.value = e.message || '注册失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-logo big">LF</div>
        <h1>LexFin</h1>
        <p>基于 RAG 的金融制度类知识问答系统</p>
      </div>

      <div class="mode-tabs">
        <button :class="{ on: mode === 'login' }" @click="mode = 'login'; error = ''">登录</button>
        <button :class="{ on: mode === 'register' }" @click="mode = 'register'; error = ''">
          注册
        </button>
      </div>

      <!-- 登录 -->
      <form v-if="mode === 'login'" class="login-form" @submit.prevent="submitLogin">
        <div class="field">
          <label class="field-label">用户名</label>
          <input v-model="loginForm.username" class="input" placeholder="请输入用户名" autocomplete="username" />
        </div>
        <div class="field">
          <label class="field-label">密码</label>
          <input
            v-model="loginForm.password"
            class="input"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </div>
        <div v-if="error" class="error-text">{{ error }}</div>
        <button class="btn submit-btn" type="submit" :disabled="loading">
          <span v-if="loading" class="spin" />{{ loading ? '登录中…' : '登 录' }}
        </button>
        <p class="hint">默认管理员：admin / Admin@123（首次部署）</p>
      </form>

      <!-- 注册 -->
      <form v-else class="login-form" @submit.prevent="submitRegister">
        <div class="field-row">
          <div class="field">
            <label class="field-label">用户名<span class="req">*</span></label>
            <input v-model="regForm.username" class="input" placeholder="4~50 位字母数字下划线" />
          </div>
          <div class="field">
            <label class="field-label">姓名</label>
            <input v-model="regForm.real_name" class="input" placeholder="选填" />
          </div>
        </div>
        <div class="field">
          <label class="field-label">密码<span class="req">*</span></label>
          <input v-model="regForm.password" class="input" type="password" placeholder="8~32 位，含字母与数字" />
        </div>
        <div class="field">
          <label class="field-label">确认密码<span class="req">*</span></label>
          <input v-model="regForm.confirm" class="input" type="password" placeholder="再次输入密码" />
        </div>
        <div class="field-row">
          <div class="field">
            <label class="field-label">邮箱</label>
            <input v-model="regForm.email" class="input" placeholder="选填" />
          </div>
          <div class="field">
            <label class="field-label">编辑邀请码</label>
            <input v-model="regForm.invite_code" class="input" placeholder="成为编辑者需填写" />
          </div>
        </div>
        <div v-if="error" class="error-text">{{ error }}</div>
        <button class="btn submit-btn" type="submit" :disabled="loading">
          <span v-if="loading" class="spin" />{{ loading ? '注册中…' : '注册并登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(1200px 500px at 70% -10%, #dbe7ff 0%, transparent 60%),
    radial-gradient(900px 400px at 10% 110%, #e5f4ef 0%, transparent 55%),
    var(--bg);
}

.login-card {
  width: 420px;
  background: var(--surface);
  border-radius: 18px;
  box-shadow: var(--shadow-lg);
  padding: 36px 40px 32px;
}

.login-brand {
  text-align: center;
  margin-bottom: 24px;
}

.brand-logo.big {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  font-size: 20px;
  border-radius: 14px;
}

.login-brand h1 {
  margin: 0;
  font-size: 24px;
  color: var(--text-1);
}

.login-brand p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-3);
}

.mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: var(--surface-2);
  border-radius: var(--radius);
  padding: 4px;
  margin-bottom: 22px;
}

.mode-tabs button {
  border: none;
  background: none;
  padding: 8px 0;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  color: var(--text-2);
}

.mode-tabs button.on {
  background: var(--surface);
  color: var(--primary);
  font-weight: 600;
  box-shadow: var(--shadow);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.submit-btn {
  padding: 10px 0;
  font-size: 15px;
}

.hint {
  margin: 0;
  text-align: center;
  color: var(--text-3);
  font-size: 12px;
}
</style>
