import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Spin } from "antd";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Market = lazy(() => import("@/pages/Market"));
const Agent = lazy(() => import("@/pages/Agent/index"));
const News = lazy(() => import("@/pages/News"));
const Fund = lazy(() => import("@/pages/Fund/index"));
const CronTasks = lazy(() => import("@/pages/CronTasks"));
const Settings = lazy(() => import("@/pages/Settings"));
const About = lazy(() => import("@/pages/About"));

import AuthGuard from "@/components/AuthGuard";

const LoadingFallback = () => (
  <div
    style={{
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      height: "60vh",
    }}
  >
    <Spin size="large" tip="加载中..." />
  </div>
);

const AppRouter: React.FC = () => {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AuthGuard>
        <Routes>
          {/* 首页为 AI 对话页 */}
          <Route path="/" element={<Agent />} />
          {/* 兼容旧链接：/agent 重定向到首页 */}
          <Route path="/agent" element={<Navigate to="/" replace />} />
          {/* 自选股移至 /watchlist */}
          <Route path="/watchlist" element={<Dashboard />} />
          <Route path="/market" element={<Market />} />
          <Route path="/news" element={<Navigate to="/news/news" replace />} />
          <Route path="/news/news" element={<News />} />
          <Route path="/news/flash" element={<News />} />
          <Route path="/fund" element={<Fund />} />
          <Route path="/fund/market" element={<Fund />} />
          <Route path="/fund/search" element={<Fund />} />
          <Route path="/fund/detail/:code" element={<Fund />} />
          <Route path="/cron-tasks" element={<CronTasks />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/notify" element={<Settings />} />
          <Route path="/settings/datasource" element={<Settings />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </AuthGuard>
    </Suspense>
  );
};

export default AppRouter;
