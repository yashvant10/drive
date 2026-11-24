"use client";
import Link from "next/link";
import { useState } from "react";
import { send } from "@/lib/api";

export function ResetForm({token}: {token?:string}) {
  const [status,setStatus] = useState<{text:string;error:boolean}>();
  const [busy,setBusy] = useState(false);
  return <div className="card form-card">
    <h1 className="page-title">{token ? "Set a new password" : "Reset your password"}</h1>
    {!(token && status && !status.error) && <form className="form" onSubmit={async event=>{
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      setBusy(true);
      setStatus(undefined);
      try {
        if (token) {
          await send("/auth/password-reset/confirm",{token,password:values.get("password")});
          setStatus({error:false,text:"Your password was updated. Sign in with your new password."});
        } else {
          const result = await send<{message:string}>("/auth/password-reset",{email:values.get("email")});
          setStatus({error:false,text:result.message});
        }
      } catch (cause) {
        setStatus({error:true,text:cause instanceof Error ? cause.message : "Try again."});
      } finally {setBusy(false);}
    }}>
      {token ? <label>New password<input required minLength={12} maxLength={128} name="password" type="password" autoComplete="new-password" /></label>
        : <label>Email<input name="email" required type="email" autoComplete="email" /></label>}
      <button className="button" disabled={busy}>{token ? "Update password" : "Send reset link"}</button>
    </form>}
    {status && <p className={status.error ? "error mb-4" : "notice"} role={status.error ? "alert" : "status"}>{status.text}</p>}
    <Link className="text-link" href="/login">Back to sign in</Link>
  </div>;
}
