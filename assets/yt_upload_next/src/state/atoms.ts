"use client";

import { atom, selector } from "recoil";

export interface UserState {
  _id: string;
  email: string;
  name?: string;
  image?: string;
  youtubeChannelId?: string;
  youtubeChannelName?: string;
  youtubeChannelImage?: string;
  youtubeConnectedAt?: string;
  sessionExpiresAt?: string;
  plan: "free" | "pro" | "enterprise";
  createdAt: string;
  updatedAt: string;
}

export const userAtom = atom<UserState | null>({
  key: "userAtom",
  default: null,
});

export const userLoadingAtom = atom<boolean>({
  key: "userLoadingAtom",
  default: true,
});

export const userDisplaySelector = selector({
  key: "userDisplaySelector",
  get: ({ get }) => {
    const user = get(userAtom);

    if (!user) {
      return {
        name: "Guest",
        email: "",
        initial: "G",
        image: null,
        plan: "free" as const,
      };
    }

    return {
      name: user.name || user.youtubeChannelName || "User",
      email: user.email,
      initial: (user.name || user.email || "U")[0].toUpperCase(),
      image: user.youtubeChannelImage || user.image || null,
      plan: user.plan,
    };
  },
});
