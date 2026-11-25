"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { send, workspaceHome, type Profile } from "@/lib/api";

const schema = z.object({name:z.string().trim().max(100), email:z.email(),password:z.string().min(12,"Use at least 12 characters.").max(128), role:z.enum(["customer","driver"])});

export function AuthForm({signup, driver, next}: {signup: boolean; driver?: boolean; next?: string}) {
  const router = useRouter();
  const [error,setError] = useState("");
  const {register, handleSubmit, setError: setFieldError, formState:{errors,isSubmitting}} = useForm<z.infer<typeof schema>>({
    resolver:zodResolver(schema), defaultValues:{role:driver ? "driver":"customer",name:"",email:"",password:""},
  });
  return <div className="card form-card"><h1 className="page-title">{signup ? "Create an account" : "Sign in"}</h1>
    <form className="form" onSubmit={handleSubmit(async data => {
      if (signup && data.name.length < 2) {setFieldError("name",{message:"Enter at least two characters."}); return;}
      setError("");
      try {
        const user = await send<Profile>(signup ? "/auth/register":"/auth/login", signup ? data : {email:data.email,password:data.password});
        const allowedNext = next && next.startsWith("/" + user.role + "/") && !next.includes("\\");
        router.replace(allowedNext ? next : workspaceHome(user.role));
        router.refresh();
      } catch (cause) {setError(cause instanceof Error ? cause.message : "Try again.");}
    })}>
      {signup && <><label>Full name<input autoComplete="name" {...register("name")} />{errors.name && <span className="error">{errors.name.message}</span>}</label>
      <label>Account type<select {...register("role")}><option value="customer">Customer</option><option value="driver">Driver</option></select></label></>}
      <label>Email<input type="email" autoComplete="email" {...register("email")} />{errors.email && <span className="error">{errors.email.message}</span>}</label>
      <label>Password<input type="password" autoComplete={signup ? "new-password":"current-password"} {...register("password")} />{errors.password && <span className="error">{errors.password.message}</span>}</label>
      {error && <p role="alert" className="error">{error}</p>}
      <Button disabled={isSubmitting} type="submit">{isSubmitting ? "Please wait…" : signup ? "Create account" : "Sign in"}</Button>
      {!signup && <Link className="text-link" href="/reset-password">Forgot password?</Link>}
    </form>
    <Link className="text-link" href={(signup ? "/login" : "/register") + (next ? "?next=" + encodeURIComponent(next) : "")}>{signup ? "Already have an account? Sign in" : "New to Drivewell? Create an account"}</Link>
  </div>;
}
