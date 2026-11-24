import { CircleDot, Gauge } from "lucide-react";

export function SteeringWheel() {
  return <span className="wheel-mark"><CircleDot size={24} /><Gauge size={13} /></span>;
}
