import Workspace from "@/components/workspace";

export default function OwnerPage() {
  return <Workspace params={Promise.resolve({role:"owner"})} searchParams={Promise.resolve({})} />;
}
