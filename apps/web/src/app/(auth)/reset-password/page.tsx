import { Footer, Header } from "@/components/site";
import { ResetForm } from "@/components/reset-form";

export default async function Reset({searchParams}: {searchParams:Promise<{token?:string}>}) {
  const {token} = await searchParams;
  return <><Header /><main className="section pale auth-page"><ResetForm token={typeof token === "string" ? token : undefined} /></main><Footer /></>;
}
