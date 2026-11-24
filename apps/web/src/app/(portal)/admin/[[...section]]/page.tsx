import Workspace from "@/components/workspace";

export default async function Page({params, searchParams}: {
  params: Promise<{section?:string[]}>; searchParams: Promise<{plan?:string}>;
}) {
  const {section} = await params;
  return <Workspace params={Promise.resolve({role:"admin", section})} searchParams={searchParams} />;
}
