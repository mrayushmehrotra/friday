"use client";

import { RecoilRoot } from "recoil";
import { ReactNode } from "react";

interface RecoilProviderProps {
    children: ReactNode;
}

export function RecoilProvider({ children }: RecoilProviderProps) {
    return <RecoilRoot>{children}</RecoilRoot>;
}
