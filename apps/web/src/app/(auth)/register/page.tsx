import { Suspense } from "react";

import { AuthForm } from "@/features/auth/components/AuthForm";

export default function RegisterPage() {
  return (
    <div className="hero-backdrop flex flex-1 items-center justify-center px-4 py-10">
      <Suspense>
        <AuthForm mode="register" />
      </Suspense>
    </div>
  );
}
