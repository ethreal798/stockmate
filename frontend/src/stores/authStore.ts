import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { getMe } from '@/api/user'

interface User{
  id: number
  username: string
  email: string
  password: string
}
interface AuthState {
  isAuthenticated: boolean
  isGuestMode: boolean // 游客模式：点击了“暂不登录”
  user: User|null
  isLoading: boolean
  // Actions
  login: () => void
  logout: () => void
  setGuestMode: (isGuest: boolean) => void
  checkAuth: () => Promise<boolean>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set,get) => ({
      isAuthenticated: false,
      isGuestMode: false,
      user: null,
      isLoading: false,

      login: () => set({   
        isAuthenticated: true, 
        isGuestMode: false,
      }),
      
      logout: () => set({ 
        isAuthenticated: false,
        isGuestMode: false,
        user: null,
      }),

      setGuestMode: (isGuest) => set({ isGuestMode: isGuest }),
      checkAuth: async () => {
        const { isAuthenticated, logout } = get()
        
        // 如果已经认证，重新获取用户信息刷新
        if (isAuthenticated) {
          set({ isLoading: true })
          try {
            // const user = await getMe()
            set({  isLoading: false })
            return true
          } catch{
            // 认证失效，调用 logout 清除状态
            logout()
            set({ isLoading: false })
            return false
          }
        }
        
        // 未认证状态，尝试验证 Cookie
        set({ isLoading: true })
        try {
          const user = await getMe()
          // 认证有效，设置用户信息
          set({
            user: user.data,
            isAuthenticated: true,
            isLoading: false,
          })
          return true
        } catch{
          // 认证无效，调用 logout 清除状态
          logout()
          set({ isLoading: false })
          return false
        }
      },
    }),
    {
      name: 'auth-storage',
      // 将数据存储在 localStorage 中
      storage: createJSONStorage(() => localStorage), 
      // 只持久化 token 和 user，不持久化游客状态，保证刷新页面重新提示
        partialize: (state) => ({  
        isAuthenticated: state.isAuthenticated 
      }),
    }
  )
)
