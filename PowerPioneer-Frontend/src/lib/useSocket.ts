import { useCallback, useEffect, useRef, useState } from "react";
import { getFreshAccessToken } from "../api/client";
import { wsUrl } from "../api/config";

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "denied";

const CLOSE_REASONS: Record<number, string> = {
  4001: "Not authenticated.",
  4003: "Direct chat is only allowed between a manager and their report, or between buddies.",
  4004: "Employee not found.",
};

/**
 * Connects to a backend WebSocket path (partial, e.g. "/ws/notifications/"),
 * authenticating with the JWT access token in the query string. Reconnects
 * with back-off unless the server refused the connection (4xxx close codes).
 */
export function useSocket<T = unknown>(path: string | null, onMessage: (data: T) => void) {
  const [status, setStatus] = useState<SocketStatus>("idle");
  const [closeReason, setCloseReason] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    if (!path) {
      setStatus("idle");
      return;
    }
    let stopped = false;
    let retry = 0;
    let everOpened = false;
    let timer: number | undefined;

    const connect = async () => {
      setStatus("connecting");
      setCloseReason(null);
      const token = await getFreshAccessToken();
      if (stopped) return;
      if (!token) {
        setStatus("denied");
        setCloseReason(CLOSE_REASONS[4001]);
        return;
      }
      const separator = path.includes("?") ? "&" : "?";
      const socket = new WebSocket(`${wsUrl(path)}${separator}token=${encodeURIComponent(token)}`);
      socketRef.current = socket;

      socket.onopen = () => {
        retry = 0;
        everOpened = true;
        setStatus("open");
      };
      socket.onmessage = (event) => {
        try {
          handlerRef.current(JSON.parse(event.data) as T);
        } catch {
          /* ignore non-JSON frames */
        }
      };
      socket.onclose = (event) => {
        socketRef.current = null;
        if (stopped) return;
        if (event.code >= 4000 && event.code < 5000) {
          setStatus("denied");
          setCloseReason(CLOSE_REASONS[event.code] ?? `Connection refused (${event.code}).`);
          return;
        }
        retry += 1;
        // The server rejects unauthorised chats during the handshake (before
        // accept), which browsers report as a generic 1006. If we have never
        // managed to connect, stop after a few tries instead of looping forever.
        if (!everOpened && retry >= 3) {
          setStatus("denied");
          setCloseReason(
            "Could not open this conversation. Direct chat is only allowed between a manager and their report, " +
              "or between buddies — or the chat server is not reachable.",
          );
          return;
        }
        setStatus("closed");
        timer = window.setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(retry, 4)));
      };
    };

    void connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [path]);

  const send = useCallback((data: unknown) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(data));
      return true;
    }
    return false;
  }, []);

  return { status, closeReason, send };
}
