"use client";

import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Info,
  Sparkles,
  X,
} from "lucide-react";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import { cn } from "@/lib/utils";

interface Notification {
  id: string;
  type: "success" | "error" | "info" | "warning" | "loading";
  title?: string;
  message: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
  persistent?: boolean;
}

interface NotificationContextType {
  notifications: Notification[];
  addNotification: (notification: Omit<Notification, "id">) => string;
  removeNotification: (id: string) => void;
  clearAllNotifications: () => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(
  undefined,
);

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error(
      "useNotifications must be used within a NotificationProvider",
    );
  }
  return context;
}

interface NotificationProviderProps {
  children: ReactNode;
}

export function NotificationProvider({ children }: NotificationProviderProps) {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const addNotification = (notification: Omit<Notification, "id">) => {
    const id = Math.random().toString(36).substr(2, 9);
    const newNotification = { ...notification, id };

    setNotifications((prev) => [...prev, newNotification]);

    // Auto-remove notification after duration (unless persistent)
    if (!notification.persistent && notification.type !== "loading") {
      const duration = notification.duration || 5000;
      setTimeout(() => {
        removeNotification(id);
      }, duration);
    }

    return id;
  };

  const removeNotification = (id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  const clearAllNotifications = () => {
    setNotifications([]);
  };

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        addNotification,
        removeNotification,
        clearAllNotifications,
      }}
    >
      {children}
      <NotificationContainer />
    </NotificationContext.Provider>
  );
}

function NotificationContainer() {
  const { notifications, removeNotification } = useNotifications();

  return (
    <div className="fixed top-4 right-4 z-[9999] space-y-2 max-w-sm w-full">
      {notifications.map((notification) => (
        <NotificationItem
          key={notification.id}
          notification={notification}
          onClose={() => removeNotification(notification.id)}
        />
      ))}
    </div>
  );
}

interface NotificationItemProps {
  notification: Notification;
  onClose: () => void;
}

function NotificationItem({ notification, onClose }: NotificationItemProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Trigger entrance animation
    const timer = setTimeout(() => setIsVisible(true), 10);
    return () => clearTimeout(timer);
  }, []);

  const handleClose = () => {
    setIsVisible(false);
    setTimeout(onClose, 300);
  };

  const icons = {
    success: <CheckCircle className="w-5 h-5 text-green-400" />,
    error: <AlertCircle className="w-5 h-5 text-red-400" />,
    info: <Info className="w-5 h-5 text-blue-400" />,
    warning: <AlertTriangle className="w-5 h-5 text-yellow-400" />,
    loading: <Sparkles className="w-5 h-5 text-purple-400 animate-pulse" />,
  };

  const gradients = {
    success: "from-green-500/20 to-emerald-500/20 border-green-500/30",
    error: "from-red-500/20 to-rose-500/20 border-red-500/30",
    info: "from-blue-500/20 to-cyan-500/20 border-blue-500/30",
    warning: "from-yellow-500/20 to-amber-500/20 border-yellow-500/30",
    loading: "from-purple-500/20 to-pink-500/20 border-purple-500/30",
  };

  return (
    <div
      className={cn(
        "glass-strong rounded-xl border p-4 transition-all duration-300 transform",
        gradients[notification.type],
        isVisible ? "translate-x-0 opacity-100" : "translate-x-full opacity-0",
      )}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className="flex-shrink-0 mt-0.5">{icons[notification.type]}</div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {notification.title && (
            <h4 className="text-white font-medium text-sm mb-1">
              {notification.title}
            </h4>
          )}
          <p className="text-gray-300 text-sm leading-relaxed">
            {notification.message}
          </p>

          {/* Action Button */}
          {notification.action && (
            <button
              onClick={notification.action.onClick}
              className="mt-2 text-xs font-medium text-purple-400 hover:text-purple-300 transition-colors"
            >
              {notification.action.label}
            </button>
          )}
        </div>

        {/* Close Button */}
        {!notification.persistent && (
          <button
            onClick={handleClose}
            className="flex-shrink-0 text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-white/10"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Progress Bar (for non-persistent notifications) */}
      {!notification.persistent && notification.type !== "loading" && (
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-pink-500 animate-shimmer" />
      )}
    </div>
  );
}

// Convenience functions for common notifications
export function showSuccess(message: string, title?: string) {
  const { addNotification } = useNotifications();
  return addNotification({ type: "success", title, message });
}

export function showError(message: string, title?: string) {
  const { addNotification } = useNotifications();
  return addNotification({ type: "error", title, message, duration: 7000 });
}

export function showInfo(message: string, title?: string) {
  const { addNotification } = useNotifications();
  return addNotification({ type: "info", title, message });
}

export function showWarning(message: string, title?: string) {
  const { addNotification } = useNotifications();
  return addNotification({ type: "warning", title, message, duration: 6000 });
}

export function showLoading(message: string, title?: string) {
  const { addNotification } = useNotifications();
  return addNotification({ type: "loading", title, message, persistent: true });
}

// Hook for async operations with loading states
export function useAsyncNotification<T>() {
  const { addNotification, removeNotification } = useNotifications();

  const executeAsync = async (
    asyncFn: () => Promise<T>,
    loadingMessage: string,
    successMessage?: string,
    errorMessage?: string,
  ): Promise<T | null> => {
    const loadingId = addNotification({
      type: "loading",
      message: loadingMessage,
      persistent: true,
    });

    try {
      const result = await asyncFn();
      removeNotification(loadingId);

      if (successMessage) {
        addNotification({
          type: "success",
          message: successMessage,
        });
      }

      return result;
    } catch (error) {
      removeNotification(loadingId);

      const message =
        errorMessage ||
        (error instanceof Error ? error.message : "An error occurred");
      addNotification({
        type: "error",
        message,
      });

      return null;
    }
  };

  return { executeAsync };
}
