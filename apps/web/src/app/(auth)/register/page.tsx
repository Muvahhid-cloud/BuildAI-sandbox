import { Suspense } from "react";

import { AuthForm } from "@/features/auth/components/AuthForm";

export default function RegisterPage() {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <Suspense>
        <AuthForm mode="register" />
      </Suspense>
    </div>
  );
}
