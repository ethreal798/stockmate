import { useEffect, useRef, useCallback, useState } from "react";

export type SSEErrorType =
  | "http-error"       // fetch 返回非 2xx
  | "network-error"    // fetch reject / read() throw
  | "timeout"          // watchdog 超时
  | "invalid-stream";  // response.body 为 null

export class SSEError extends Error {
  type: SSEErrorType;
  status?: number;

  constructor(type: SSEErrorType, message: string, options?: { status?: number }) {
    super(message);
    this.name = "SSEError";
    this.type = type;
    this.status = options?.status;
  }
}

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}

interface UseSSEOptions {
  onMessage?: (message: SSEMessage) => void;
  onDone?: () => void;
  onError?: (error: SSEError) => void;
}

interface ConnectOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  lastEventId?: string | null;
}

interface UseSSEReturn {
  loading: boolean;
  connect: (url: string, body?: unknown, options?: ConnectOptions) => void;
  abort: () => void;
}

const WATCHDOG_INTERVAL = 30_000;

/**
 * 按 SSE 规范剥掉字段名后的单个空格（如果存在），保留其他前导空白。
 * 规范：冒号后若紧跟一个 U+0020 SPACE，移除该空格。
 */
const stripOneLeadingSpace = (value: string): string => {
  return value.startsWith(" ") ? value.slice(1) : value;
};

export const useSSE = (options: UseSSEOptions = {}): UseSSEReturn => {
  const { onMessage, onDone, onError } = options;
  const abortControllerRef = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(false);

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
    setLoading(false);
  }, []);

  const connect = useCallback(
    async (url: string, body?: unknown, options?: ConnectOptions) => {
      // 先中止上一次请求
      abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      setLoading(true);

      let watchdogTimer: ReturnType<typeof setTimeout> | null = null;
      const resetWatchdog = () => {
        if (watchdogTimer) clearTimeout(watchdogTimer);
        watchdogTimer = setTimeout(() => {
          onError?.(new SSEError("timeout", "SSE heartbeat timeout"));
          abort();
        }, WATCHDOG_INTERVAL);
      };
      const clearWatchdog = () => {
        if (watchdogTimer) {
          clearTimeout(watchdogTimer);
          watchdogTimer = null;
        }
      };

      let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

      try {
        const method = options?.method ?? "POST";

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

        if (method !== "GET") {
          headers["Content-Type"] = "application/json";
          init.body = JSON.stringify(body ?? {});
        }
        const response = await fetch(url, init);

        if (!response.ok) {
          throw new SSEError("http-error", `HTTP error! status: ${response.status}`, { status: response.status });
        }

        reader = response.body?.getReader() ?? null;
        if (!reader) {
          throw new SSEError("invalid-stream", "Response body is not readable");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let stopped = false;

        /**
         * 处理单个事件块（两个双换行之间的内容）。
         * @returns true 表示收到了 done 事件，应提前终止读取循环
         */
        const processEventBlock = (block: string): boolean => {
          const lines = block.split(/\r?\n/);
          let eventName = "message";
          let eventId: string | undefined = undefined;
          let retryMs: number | undefined = undefined;
          const dataLines: string[] = [];

          for (const line of lines) {
            if (line.startsWith("id:")) {
              eventId = stripOneLeadingSpace(line.slice(3));
              continue;
            }
            if (line.startsWith("event:")) {
              eventName = stripOneLeadingSpace(line.slice(6));
              continue;
            }
            if (line.startsWith("retry:")) {
              const ms = parseInt(stripOneLeadingSpace(line.slice(6)), 10);
              if (Number.isFinite(ms) && ms >= 0) retryMs = ms;
              continue;
            }
            if (line.startsWith("data:")) {
              dataLines.push(stripOneLeadingSpace(line.slice(5)));
            }
          }

          // 按规范：多个 data 行用 \n 连接，恰好一个尾随换行应被移除
          let data = dataLines.join("\n");
          if (data.endsWith("\n")) {
            data = data.slice(0, -1);
          }

          if (data) {
            onMessage?.({ event: eventName, data, id: eventId, retry: retryMs });
          }

          if (eventName === "done") {
            onDone?.();
            setLoading(false);
            return true;
          }

          return false;
        };

        // 启动 watchdog
        resetWatchdog();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          // 收到数据，重置 watchdog
          resetWatchdog();

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() ?? "";
          for (const block of blocks) {
            if (!block.trim()) continue;
            if (processEventBlock(block)) {
              stopped = true;
              reader.releaseLock();
              clearWatchdog();
              return;
            }
          }
        }

        // 流正常结束：flush decoder 获取 UTF-8 多字节序列尾
        buffer += decoder.decode();
        // 派发最后一个残块（如果没等来双换行）
        if (buffer.trim()) {
          processEventBlock(buffer);
        }

        // 显式释放 ReadableStream reader 的锁
        reader.releaseLock();
        clearWatchdog();

        if (!stopped) {
          onDone?.();
          setLoading(false);
        }
      } catch (error) {
        clearWatchdog();
        // abort() 会让 reader.read() reject，但锁仍被持有，需要显式释放
        if (reader) reader.releaseLock();
        if ((error as Error).name === "AbortError") {
          // 用户主动中止
          return;
        }
        if (error instanceof SSEError) {
          // HTTP 错误 / invalid-stream 直接透传
          onError?.(error);
        } else {
          onError?.(new SSEError("network-error", (error as Error).message));
        }
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
