import { NewPasswordForm } from "@/components/AccountActions";

export const metadata = { title: "Nouveau mot de passe" };

export default function NewPassword() {
  return (
    <div className="mx-auto max-w-sm pt-4">
      <h1 className="px-1 font-display text-2xl font-bold tracking-tight">Nouveau mot de passe</h1>
      <NewPasswordForm />
    </div>
  );
}
