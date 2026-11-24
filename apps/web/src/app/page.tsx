import Image from "next/image";
import { Button } from "@/components/ui/button";
import { HeroNote } from "@/components/hero-note";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, CalendarDays, CarFront, Check, ChevronDown, Clock3, Headphones, MapPin, ShieldCheck, UserRoundCheck } from "lucide-react";
import { Footer, Header } from "@/components/site";
import { faqs } from "@/lib/content";

const steps = [
  { icon: CalendarDays, title: "Tell us when and where", description: "Choose your car, pickup point and when you need a driver." },
  { icon: UserRoundCheck, title: "Request a driver", description: "Review your fare and request a driver who can handle your car." },
  { icon: CarFront, title: "Sit back in your own car", description: "Check your booking for assignment and pickup updates." },
];

export default function Home() {
  return <><Header /><main>
    <section className="hero-shell"><div className="wrap hero">
      <div className="hero-copy"><span className="eyebrow hero-location"><MapPin size={15} /> Bengaluru, Karnataka</span>
      <h1>Your car.<br />Your driver.<br /><em>Your time.</em></h1>
      <p>Hire a professional driver for your own car. From quick errands to full-day plans, make every trip yours.</p>
      <div className="hero-actions"><Button asChild><Link href="/customer/book">Book a driver <ArrowUpRight size={18} /></Link></Button><Link href="#how" className="hero-link">How it works <ArrowRight size={17} /></Link></div></div>
      <div className="hero-image"><Image src="/chauffeur.webp" alt="Professional chauffeur beside a dark sedan at a modern drop-off" priority fill sizes="(max-width: 760px) 100vw, 55vw" /><HeroNote /></div>
    </div></section>
    <div className="trust"><div className="wrap trust-inner"><span><ShieldCheck /> Approved drivers</span><span><CarFront /> Your own vehicle</span><span><Clock3 /> Flexible durations</span><span><Headphones /> In-app support</span></div></div>
    <section className="wrap section" id="how"><div className="section-intro"><span className="eyebrow">HOW IT WORKS</span><h2>A driver in three simple steps.</h2><p>Choose your car and see your fare before you send a request.</p></div><div className="cards">{steps.map(({icon: Icon,title,description}) => <article className="card" key={title}><span className="tile-icon"><Icon size={23} /></span><h3>{title}</h3><p>{description}</p></article>)}</div></section>
    <section className="pale"><div className="wrap section"><div className="section-intro"><span className="eyebrow">BOOKING OPTIONS</span><h2>Make room for your plans.</h2><p>Choose the time you need and get an itemised quote.</p></div><div className="cards">{[["Hourly", "For errands, appointments and quick trips.", "hourly"], ["Half day", "Four hours for a few stops across town.", "half-day"], ["Full day", "Eight hours for meetings, events and longer plans.", "full-day"]].map(([label, copy, plan]) => <Link className="card service-card" href={"/customer/book?plan=" + plan} key={plan}><span className="tile-icon"><Clock3 size={23} /></span><h3>{label}</h3><p>{copy}</p><span className="text-link">Request a driver <ArrowRight size={16} /></span></Link>)}</div></div></section>
    <section className="wrap section split"><div><span className="eyebrow">SAFETY</span><h2>Know who’s behind the wheel.</h2><p>Find your assignment in your booking details and get help through the support portal.</p><Link className="text-link" href="/safety">Explore safety <ArrowRight size={17} /></Link></div><div className="check-list">{["Driver approval required to accept requests", "Vehicle and transmission compatibility", "Booking status recorded as it changes"].map(label => <p key={label}><Check size={20} />{label}</p>)}</div></section>
    <section className="pale"><div className="wrap section faq"><div className="section-intro"><span className="eyebrow">FAQ</span><h2>Good to know.</h2></div>{faqs.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={18} /></summary><p>{answer}</p></details>)}</div></section>
    <section className="wrap section driver-cta"><div><span className="eyebrow">DRIVE WITH US</span><h2>Drive on your terms.</h2><p>Create a driver account and set up your service preferences.</p></div><Link href="/become-a-driver" className="button">Become a driver <ArrowUpRight size={18} /></Link></section>
  </main><Footer /></>;
}
