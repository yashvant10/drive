"use client";

import { motion, useReducedMotion } from "motion/react";
import { ShieldCheck } from "lucide-react";

export function HeroNote() {
  const reduce = useReducedMotion();
  return <motion.div className="image-note" initial={false} animate={{y:0}} whileHover={reduce?undefined:{y:-3}} transition={{duration:0.18}}>
    <span><ShieldCheck size={20} /></span><div><strong>Driver approval</strong><small>Required before accepting requests</small></div>
  </motion.div>;
}
