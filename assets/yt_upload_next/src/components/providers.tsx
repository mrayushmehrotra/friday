"use client";

import { RecoilRoot } from "recoil";
import { ReactNode } from "react";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return <RecoilRoot>{children}</RecoilRoot>;
}
