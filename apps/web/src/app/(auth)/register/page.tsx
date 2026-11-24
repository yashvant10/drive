import { AuthForm } from "@/components/auth-form";
import { Header, Footer } from "@/components/site";

export default async function Register({searchParams}: {searchParams:Promise<{role?:string;next?:string}>}) {
  const {role,next} = await searchParams;
  return <><Header /><main className="section pale auth-page"><AuthForm signup driver={role === "driver"} next={typeof next === "string" ? next : undefined} /></main><Footer /></>;
}
