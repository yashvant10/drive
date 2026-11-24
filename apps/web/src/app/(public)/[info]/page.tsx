import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Footer, Header } from "@/components/site";
import { faqs } from "@/lib/content";

const content: Record<string, { title: string; intro: string; sections?: string[][]; action?: [string, string] }> = {
  "how-it-works": { title:"How Drivewell works", intro:"Hire a professional to drive your own car in Bengaluru.", sections:[["Add your car","Sign in and save your car and its transmission."],["Request a driver","Choose a time and pickup point, review the fare, then submit your request."],["Follow your booking","Use your booking details to see whether a driver has accepted and follow pickup updates."]], action:["Book a driver","/customer/book"] },
  services: { title:"A driver for the time you need",intro:"Book for a few hours, half a day or a full day in Bengaluru.", sections:[["Hourly","Choose a duration for errands, short outings or appointments."],["Half day","Request four hours for a flexible itinerary."],["Full day","Request eight hours for events, meetings or longer days."]],action:["View pricing","/pricing"] },
  pricing: { title:"See the fare before you request", intro:"Your quote is calculated in INR and includes a base charge and a service charge for your chosen duration.",sections:[["Hourly, half-day and full-day prices","Sign in, select a vehicle and use the booking form to get your current quote."],["Payments","If online payment is enabled for your booking, you can use Razorpay checkout after the driver marks arrival. Your payment history shows confirmed captures."]],action:["Get a quote","/customer/book"] },
  safety: { title:"Safety on Drivewell", intro:"Driver approval is required before a driver can accept a booking.",sections:[["Compatibility","Requests are matched using the service area and vehicle transmission."],["Booking and support records","Review assignment updates in your booking. Signed-in users can open a support ticket from their workspace."],["Emergency assistance","Call 112 in India if someone is in immediate danger. Drivewell support does not contact emergency services."]],action:["Contact support","/contact"] },
  "become-a-driver": {title:"Drive with Drivewell",intro:"Create a driver account to set your service preferences for Bengaluru.",sections:[["Set your preferences","Tell us which transmissions you can drive."],["Approval","Your profile must be approved before you can go online or accept a booking. Upload your current driving licence from your driver workspace for review."]],action:["Create driver account","/register?role=driver"]},
  contact: {title:"Contact Drivewell",intro:"Sign in and open Support in your account to submit a ticket. Include your booking reference when requesting trip help.",action:["Sign in","/login"]},
  faq: {title:"Frequently asked questions",intro:"Common questions about requesting a driver in Bengaluru.",sections:faqs},
  privacy: {title:"Privacy information",intro:"Drivewell uses the details you submit to manage your account and booking requests.",sections:[["Data used","The platform stores account information, vehicle details, requested pickup and destination, and support messages."],["Session cookies","A necessary session cookie keeps you signed in. Use the sign-out control to end your session."],["Questions","Open a support ticket from your account for privacy-related requests."]]},
  terms: {title:"Booking terms",intro:"Drivewell helps customers request a driver for a customer-owned vehicle in Bengaluru.",sections:[["Requests and assignments","A submitted request remains pending until a driver accepts it. Supply accurate pickup and vehicle information."],["Cancellation","You can cancel a booking before the driver marks arrival."],["Service availability","Use your booking details to check the current status."]]},
};

export default async function Information({params}: {params: Promise<{info:string}>}) {
  const {info} = await params;
  if (!Object.hasOwn(content, info)) notFound();
  const data = content[info];
  return <><Header /><main className="wrap section subpage"><h1 className="page-title">{data.title}</h1><p>{data.intro}</p>{data.sections?.map(([title, copy]) => <section key={title}><h2>{title}</h2><p>{copy}</p></section>)}{data.action && <Link className="button" href={data.action[1]}>{data.action[0]} <ArrowUpRight size={17} /></Link>}</main><Footer /></>;
}
