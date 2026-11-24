import Link from "next/link";
import { SteeringWheel } from "./mark";

export function Brand() {
  return <Link href="/" className="brand"><span className="brand-icon"><SteeringWheel /></span>drivewell<span className="brand-dot">.</span></Link>;
}
