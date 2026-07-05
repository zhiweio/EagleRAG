import {
  listNotificationsApiNotificationsGet,
  patchNotificationNotificationsNotificationIdPatch,
  readAllNotificationsNotificationsReadAllPost,
} from "@/lib/api/generated/sdk.gen";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body: string;
  kb_name?: string | null;
  job_id?: string | null;
  read: boolean;
  created_at: string;
}

export function useNotifications(params?: { read?: boolean; limit?: number }, enabled = true) {
  return useQuery({
    queryKey: ["notifications", params],
    enabled,
    queryFn: async () => {
      const result = await listNotificationsApiNotificationsGet({
        query: { read: params?.read, limit: params?.limit ?? 50, offset: 0 },
      });
      if (result.error) throw result.error;
      const d = result.data as {
        items?: NotificationItem[];
        unread_count?: number;
      };
      return {
        items: d.items ?? [],
        unreadCount: d.unread_count ?? 0,
      };
    },
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await patchNotificationNotificationsNotificationIdPatch({
        path: { notification_id: id },
      });
      if (result.error) throw result.error;
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await readAllNotificationsNotificationsReadAllPost();
      if (result.error) throw result.error;
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
