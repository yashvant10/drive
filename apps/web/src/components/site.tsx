import Link from "next/link";
import { ArrowUpRight, Menu } from "lucide-react";
import { Brand } from "./brand";

const links = [["How it works", "/how-it-works"], ["Services", "/services"], ["Pricing", "/pricing"], ["Safety", "/safety"]];

export function Header() {
  return <header className="header"><div className="wrap nav"><Brand /><nav className="desktop-nav" aria-label="Main navigation">{links.map(([label, url]) => <Link key={url} href={url}>{label}</Link>)}</nav><div className="nav-actions"><Link href="/login" className="sign-in">Sign in</Link><Link href="/customer/book" className="button compact">Book a driver <ArrowUpRight size={15} /></Link></div><details className="mobile-nav"><summary aria-label="Navigation"><Menu /></summary><nav aria-label="Mobile navigation">{[...links, ["Sign in", "/login"], ["Book a driver", "/customer/book"]].map(([label, url]) => <Link key={url} href={url}>{label}</Link>)}</nav></details></div></header>;
}

export function Footer() {
  return <footer><div className="wrap footer-grid"><div><Brand /><p>Professional drivers for your own car.<br />Built for Bengaluru, Karnataka.</p></div><div><strong>Explore</strong>{links.map(([label, url]) => <Link href={url} key={url}>{label}</Link>)}</div><div><strong>Company</strong><Link href="/become-a-driver">Become a driver</Link><Link href="/contact">Contact</Link><Link href="/faq">FAQs</Link></div><div><strong>Legal</strong><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link></div></div><div className="wrap footer-bottom">© {new Date().getFullYear()} Drivewell</div></footer>;
}
