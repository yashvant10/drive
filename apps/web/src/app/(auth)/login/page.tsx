import { AuthForm } from "@/components/auth-form";
import { Header, Footer } from "@/components/site";

export default async function Login({searchParams}: {searchParams:Promise<{next?:string}>}) {
  const {next} = await searchParams;
  return <><Header /><main className="section pale auth-page"><AuthForm signup={false} next={typeof next === "string" ? next : undefined} /></main><Footer /></>;
}
