import {
  getMeUsersMeGet,
  getMyPreferencesUsersMePreferencesGet,
  patchMeUsersMePatch,
  patchMyPreferencesUsersMePreferencesPatch,
} from "@/lib/api/generated/sdk.gen";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface UserProfile {
  user_id: string;
  display_name: string;
  avatar_initials: string;
  locale: string;
}

export interface UserPreferences {
  default_kb_name?: string;
  notifications_enabled?: boolean;
  ingest_poll_interval_ms?: number;
  [key: string]: unknown;
}

export function useUser() {
  return useQuery({
    queryKey: ["user", "me"],
    queryFn: async () => {
      const result = await getMeUsersMeGet();
      if (result.error) throw result.error;
      return result.data as UserProfile;
    },
  });
}

export function useUserPreferences() {
  return useQuery({
    queryKey: ["user", "preferences"],
    queryFn: async () => {
      const result = await getMyPreferencesUsersMePreferencesGet();
      if (result.error) throw result.error;
      return result.data as UserPreferences;
    },
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      display_name?: string;
      avatar_initials?: string;
      locale?: string;
    }) => {
      const result = await patchMeUsersMePatch({ body });
      if (result.error) throw result.error;
      return result.data as UserProfile;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user"] });
    },
  });
}

export function useUpdateUserPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: UserPreferences) => {
      const result = await patchMyPreferencesUsersMePreferencesPatch({ body });
      if (result.error) throw result.error;
      return result.data as UserPreferences;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", "preferences"] });
    },
  });
}
