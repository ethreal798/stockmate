import { useEffect, useRef, useCallback, useState } from "react";

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

interface UseSSEOptions {
  onMessage?: (message: SSEMessage) => void;
  onDone?: () => void;
  onError?: (error: Event) => void;
}

interface SSEConnectOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  lastEventId?: string | null;
}

interface UseSSEReturn {
  loading: boolean;
  connect: (url: string, body?: unknown, options?: SSEConnectOptions) => void;
  abort: () => void;
}

export const useSSE = (options: UseSSEOptions = {}): UseSSEReturn => {
  // 解构获取用户传入的回调函数
  const { onMessage, onDone, onError } = options;
  const abortControllerRef = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(false);
  // 中止当前请求
  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
    setLoading(false);
  }, []);

  const connect = useCallback(
    async (url: string, body?: unknown, options?: SSEConnectOptions) => {
      // 先中止上一次请求
      abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      setLoading(true);

      try {
        const method = options?.method ?? "POST";
        // 构建请求头，包括用户自定义的头和 Last-Event-ID
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          ...(options?.headers ?? {}),
          ...(options?.lastEventId
            ? { "Last-Event-ID": options.lastEventId }
            : {}),
        };
        const init: RequestInit = {
          method,
          headers,
          signal: controller.signal,
        };
        // 如果是 POST 请求，需要设置 Content-Type 并将 body 转换为 JSON 字符串
        if (method !== "GET") {
          headers["Content-Type"] = "application/json";
          init.body = JSON.stringify(body ?? {});
        }
        const response = await fetch(url, init);

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("Response body is not readable");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        // 处理每个事件块，提取事件名、事件ID和数据
        const processEventBlock = (block: string) => {
          const lines = block.split(/\r?\n/);
          let eventName = "message";
          let eventId: string | undefined = undefined;
          const dataLines: string[] = [];

          for (const line of lines) {
            if (line.startsWith("id:")) {
              eventId = line.slice(3).trim();
              continue;
            }
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
              continue;
            }
            if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trimStart());
            }
          }

          const data = dataLines.join("\n").trim();
          if (data === "[DONE]") {
            onDone?.();
            setLoading(false);
            return true;
          }

          if (data) {
            onMessage?.({ event: eventName, data, id: eventId });
          }

          if (eventName === "done") {
            onDone?.();
            setLoading(false);
            return true;
          }

          return false;
        };
        // 读取响应体，直到完成或中止请求
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() ?? "";
          for (const block of blocks) {
            if (!block.trim()) continue;
            const shouldStop = processEventBlock(block);
            if (shouldStop) {
              return;
            }
          }
        }

        onDone?.();
        setLoading(false);
      } catch (error) {
        if ((error as Error).name === "AbortError") {
          // 用户主动中止
          return;
        }
        onError?.(error as Event);
        setLoading(false);
      }
    },
    [abort, onMessage, onDone, onError],
  );

  useEffect(() => {
    return () => {
      abort();
    };
  }, [abort]);

  return { loading, connect, abort };
};
