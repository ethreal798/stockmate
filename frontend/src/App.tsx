import React, { useState } from "react";
import { BrowserRouter } from "react-router-dom";
import {
  ConfigProvider,
  Layout,
  Menu,
  theme,
  Dropdown,
  Space,
  Avatar,
  Button,
  Typography,
} from "antd";
import type { MenuProps } from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  DashboardOutlined,
  StockOutlined,
  RobotOutlined,
  NotificationOutlined,
  FundOutlined,
  ClockCircleOutlined,
  SettingOutlined,
  InfoCircleOutlined,
  UserOutlined,
  LogoutOutlined,
  LoginOutlined,
} from "@ant-design/icons";
import { useNavigate, useLocation, Routes, Route } from "react-router-dom";
import AppRouter from "./router";
import Login from "@/pages/Login";
import { logoutApi } from "@/api/auth";
import { useAuthStore } from "@/stores/authStore";
import "dayjs/locale/zh-cn";
import dayjs from "dayjs";

dayjs.locale("zh-cn");

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

const pageTitleMap: Record<string, string> = {
  "/": "AI 对话",
  "/watchlist": "自选股",
  "/market": "行情中心",
  "/news": "新闻资讯",
  "/news/news": "新闻",
  "/news/flash": "快讯",
  "/fund": "我的关注",
  "/fund/market": "基金排行",
  "/cron-tasks": "定时任务",
  "/settings": "AI 配置",
  "/settings/notify": "通知配置",
  "/settings/datasource": "数据源配置",
  "/about": "关于",
};

const menuItems: MenuProps["items"] = [
  { key: "/", icon: <RobotOutlined />, label: "AI 对话" },
  {
    key: "/fund",
    icon: <FundOutlined />,
    label: "基金",
    children: [
      { key: "/fund", label: "我的关注" },
      { key: "/fund/market", label: "基金排行" },
    ],
  },
  {
    key: "/news",
    icon: <NotificationOutlined />,
    label: "新闻资讯",
    children: [{ key: "/news/flash", label: "快讯" }],
  },
  { key: "/watchlist", icon: <DashboardOutlined />, label: "自选股" },
  { key: "/market", icon: <StockOutlined />, label: "行情中心" },
  { key: "/cron-tasks", icon: <ClockCircleOutlined />, label: "定时任务" },
  {
    key: "/settings",
    icon: <SettingOutlined />,
    label: "设置",
    children: [
      { key: "/settings", label: "AI 配置" },
      { key: "/settings/notify", label: "通知配置" },
      { key: "/settings/datasource", label: "数据源配置" },
    ],
  },
  { key: "/about", icon: <InfoCircleOutlined />, label: "关于" },
];

// 根据当前 pathname 映射到一级菜单标题，用于 Header 展示（不递归子菜单）
const getTopMenuLabel = (
  items: MenuProps["items"] | undefined,
  pathname: string,
): React.ReactNode | null => {
  if (!items) return null;

  for (const item of items) {
    if (!item) continue;
    if (!("key" in item)) continue;

    const key = item.key;
    if (typeof key !== "string") continue;

    if (key === pathname) {
      return "label" in item ? item.label : null;
    }

    if (key !== "/" && pathname.startsWith(key)) {
      return "label" in item ? item.label : null;
    }
  }

  return null;
};

// 主布局：包含侧边栏菜单、顶部 Header、以及路由内容区
const AppLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, logout } = useAuthStore();
  const handleLogout = async () => {
    logout(); //前端退出登录
    await logoutApi(); //后端退出登录
    navigate("/login");
  };
  const currentTitle =
    (location.pathname.startsWith("/fund/detail/")
      ? "基金详情"
      : pageTitleMap[location.pathname]) ??
    getTopMenuLabel(menuItems, location.pathname) ??
    "StockMate";

  const userMenuItems: MenuProps["items"] = [
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "退出登录",
      onClick: () => handleLogout(),
    },
  ];

  return (
    <Layout style={{ height: "100vh", overflow: "hidden" }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        width={150}
        collapsedWidth={50}
        style={{ overflowY: "auto" }}
      >
        <div
          style={{
            height: 48,
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: collapsed ? 0 : 8,
            padding: collapsed ? 0 : "0 16px",
            color: "#001529",
            fontSize: collapsed ? 20 : 16,
            fontWeight: 700,
            overflow: "hidden",
            whiteSpace: "nowrap",
            transition: "all 0.2s",
            borderBottom: "1px solid rgba(255,255,255,0.1)",
            marginBottom: 4,
          }}
        >
          <img
            src="/stock.svg"
            alt="StockMate"
            style={{ width: 20, height: 20, display: "block", flexShrink: 0 }}
          />
          {!collapsed && <span>StockMate</span>}
        </div>
        <Menu
          theme="light"
          selectedKeys={[location.pathname]}
          mode="inline"
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout style={{ overflow: "hidden" }}>
        <Header
          style={{
            padding: "0 24px",
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            boxShadow: "0 1px 4px rgba(0,21,41,.08)",
            height: 48,
            lineHeight: "48px",
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 600, color: "#1d2129" }}>
            {currentTitle}
          </span>

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {isAuthenticated ? (
              <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
                <Space style={{ cursor: "pointer", padding: "0 8px" }}>
                  <Avatar
                    size="small"
                    icon={<UserOutlined />}
                    style={{ backgroundColor: "#1677ff" }}
                  />
                  <Text
                    strong
                    style={{ maxWidth: 100 }}
                    ellipsis={{ tooltip: "" }}
                  >
                    已登录
                  </Text>
                </Space>
              </Dropdown>
            ) : (
              <Button
                type="primary"
                icon={<LoginOutlined />}
                onClick={() => navigate("/login")}
              >
                登录
              </Button>
            )}
          </div>
        </Header>
        <Content
          style={{
            margin: 0,
            padding: 16,
            height: "calc(100vh - 48px)",
            background: "#f0f2f5",
            overflowY: "auto",
          }}
        >
          <AppRouter />
        </Content>
      </Layout>
    </Layout>
  );
};

// 应用入口：提供 Ant Design 主题/国际化，并挂载路由
const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 6,
        },
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={<AppLayout />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;
