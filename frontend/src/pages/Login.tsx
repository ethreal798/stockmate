import React, { useState } from "react";
import {
  Form,
  Input,
  Button,
  Col,
  Typography,
  message,
  Divider,
  Alert,
} from "antd";
import { UserOutlined, LockOutlined, MailOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { login, register } from "@/api/auth";
import LiveKLineChart from "@/components/LiveKLineChart";

const { Title, Text } = Typography;

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const navigate = useNavigate();
  const loginStore = useAuthStore((state) => state.login);
  const [form] = Form.useForm();

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      if (isRegister) {
        await register({
          email: values.email,
          username: values.username,
          password: values.password,
        });
        loginStore();
        message.success("注册并登录成功");
      } else {
        const formData = new FormData();
        formData.append("username", values.email);
        formData.append("password", values.password);
        const res = await login(formData);
        console.log(res);
        loginStore();
        message.success("登录成功");
      }
      navigate("/");
    } catch (error: any) {
      if (error.response?.status === 401) {
        console.error(error.response.data.msg || "邮箱或密码错误");
      } else {
        console.error(isRegister ? "注册失败" : "登录失败");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        overflow: "hidden",
        background:
          "radial-gradient(ellipse 60% 80% at 12% 50%, rgba(22,119,255,0.07) 0%, rgba(22,119,255,0.025) 45%, transparent 70%), linear-gradient(90deg, rgba(22,119,255,0.04) 0%, rgba(22,119,255,0.015) 30%, rgba(255,255,255,0) 60%), #ffffff",
      }}
    >
      <Col
        span={17}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#1a1a1a",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 960,
            textAlign: "center",
            position: "relative",
            zIndex: 1,
          }}
        >
          <Title
            style={{
              color: "#1a1a1a",
              fontSize: "48px",
              marginBottom: 8,
              letterSpacing: "-0.5px",
            }}
          >
            StockMate
          </Title>
          {/* <Text
            style={{
              color: "rgba(0,0,0,0.45)",
              fontSize: "17px",
              letterSpacing: "0.5px",
            }}
          >
            基金分析与量化交易小助手
          </Text> */}

          <div
            style={{
              marginTop: "40px",
              width: "100%",
              height: "460px",
              overflow: "hidden",
              position: "relative",
            }}
          >
            <LiveKLineChart speed={1.8} candleCount={55} />
          </div>
        </div>
      </Col>

      <Col
        span={7}
        style={{
          padding: "0 40px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        <div style={{ maxWidth: "400px", width: "100%", margin: "0 auto" }}>
          <div style={{ marginBottom: "40px", textAlign: "center" }}>
            <Title level={2}>{isRegister ? "创建账号" : "欢迎回来"}</Title>
            <Text type="secondary">
              {isRegister
                ? "请输入您的基本信息开始体验"
                : "请输入您的邮箱和密码进行登录"}
            </Text>
          </div>

          <Form
            form={form}
            name="auth_form"
            layout="vertical"
            initialValues={{
              email: "14750995319@163.com",
              password: "123456",
            }}
            onFinish={onFinish}
            autoComplete="off"
            size="large"
          >
            <Form.Item
              label="邮箱"
              name="email"
              rules={[
                { required: true, message: "请输入您的邮箱" },
                { type: "email", message: "请输入有效的邮箱地址" },
              ]}
            >
              <Input prefix={<MailOutlined />} placeholder="example@mail.com" />
            </Form.Item>

            {isRegister && (
              <Form.Item
                label="用户名"
                name="username"
                rules={[{ required: true, message: "请输入用户名" }]}
              >
                <Input prefix={<UserOutlined />} placeholder="jie798" />
              </Form.Item>
            )}

            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="******" />
            </Form.Item>

            {!isRegister && (
              <Alert
                message="先使用默认账号快速体验吧！"
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}

            <Form.Item style={{ marginTop: "24px" }}>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                style={{ height: "45px" }}
              >
                {isRegister ? "注册并登录" : "立即登录"}
              </Button>
            </Form.Item>
          </Form>

          <Divider plain>
            <Text type="secondary" style={{ fontSize: "12px" }}>
              其他操作
            </Text>
          </Divider>

          <div style={{ textAlign: "center" }}>
            <Button
              type="link"
              onClick={() => {
                setIsRegister(!isRegister);
                form.resetFields();
              }}
            >
              {isRegister ? "已有账号？立即登录" : "还没有账号？点击注册"}
            </Button>
          </div>
        </div>
      </Col>
    </div>
  );
};

export default Login;
