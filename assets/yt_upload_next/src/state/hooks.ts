"use client";

import { useEffect, useCallback } from "react";
import { useRecoilState, useSetRecoilState } from "recoil";
import {
  userAtom,
  userLoadingAtom,
  type UserState,
} from "./atoms";

export function useUserData() {
  const [user, setUser] = useRecoilState(userAtom);
  const [isLoading, setIsLoading] = useRecoilState(userLoadingAtom);

  const fetchUserData = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await fetch("/api/user", {
        credentials: "include",
      });

      if (!response.ok) {
        if (response.status === 401) {
          setUser(null);
          return { authenticated: false };
        }
        throw new Error("Failed to fetch user data");
      }

      const data = await response.json();

      if (data.success && data.authenticated) {
        setUser(data.user);
        return { authenticated: true, user: data.user };
      } else {
        setUser(null);
        return { authenticated: false };
      }
    } catch (error) {
      console.error("Error fetching user data:", error);
      setUser(null);
      return { authenticated: false, error };
    } finally {
      setIsLoading(false);
    }
  }, [setUser, setIsLoading]);

  return {
    user,
    isLoading,
    fetchUserData,
  };
}

export function useInitializeUser() {
  const { fetchUserData, isLoading } = useUserData();

  useEffect(() => {
    fetchUserData();
  }, [fetchUserData]);

  return { isLoading };
}
