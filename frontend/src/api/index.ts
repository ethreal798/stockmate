import axios from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'
import { message } from 'antd'
import {useAuthStore} from '@/stores/authStore'
import { refreshApi } from './auth'

interface RetryConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  _isRefresh?: boolean
}

// 刷新锁与并发重试队列：多个请求同时 401 时只刷新一次，其余挂起等待
let isRefreshing = false
let pendingRequests: Array<(ok: boolean) => void> = []

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  },
)

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    const res = response.data

    // 后端可能返回 null（例如无数据的分页接口），视为业务成功，直接放行
    if (res == null) {
      return response.data
    }
    if (res.code !== 1) {
      message.error(res.msg || '请求失败')
      return Promise.reject(new Error(res.msg || '请求失败'))
    }
    return res
  },
  async (error) => {
    const config = (error.config || {}) as RetryConfig

    // 401 处理：区分 token 过期 / 密码错误 / refresh 失效
    // 后端 body code 实际是 0（非 401），故用 HTTP 状态码判定
    if (error.response?.status === 401) {
      const isLoginReq =
        typeof config.url === 'string' && config.url.includes('/auth/login')

      // 豁免：refresh 自身失效 —— 静默拒绝，交由外层 try/catch 统一处理
      if (config._isRefresh) {
        return Promise.reject(error)
      }

      // 豁免：重试后仍 401 —— 视为真失效，登出
      if (config._retry) {
        message.error('登录已过期，请重新登录')
        useAuthStore.getState().logout()
        return Promise.reject(error)
      }

      // 豁免：登录密码错误 —— 提示并拒绝，不触发刷新
      if (isLoginReq) {
        const res = error.response.data
        message.error(res?.msg || '未授权，请重新登录')
        return Promise.reject(error)
      }

      // 并发场景：已有刷新在进行，挂起等待结果
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingRequests.push((ok) => {
            if (ok) {
              config._retry = true
              resolve(request(config))
            } else {
              reject(error)
            }
          })
        })
      }

      // 发起刷新
      config._retry = true
      isRefreshing = true
      try {
        await refreshApi()
        // 刷新成功，释放队列并重试原请求
        pendingRequests.forEach((cb) => cb(true))
        pendingRequests = []
        return request(config)
      } catch (refreshError) {
        // 刷新失败，释放队列并登出
        pendingRequests.forEach((cb) => cb(false))
        pendingRequests = []
        message.error('登录已过期，请重新登录')
        useAuthStore.getState().logout()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // 其他 HTTP 错误
    if (error.response) {
      const res = error.response.data
      message.error(res?.msg || '请求失败')
    } else if (error.request) {
      message.error('网络连接失败，请检查网络')
    } else {
      message.error(error.message || '未知错误')
    }
    return Promise.reject(error)
  },
)

export default request
