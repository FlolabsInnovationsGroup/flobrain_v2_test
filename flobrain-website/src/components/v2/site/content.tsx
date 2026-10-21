import {
  BookOpen,
  Bot,
  Building2,
  Cloud,
  Coins,
  Database,
  EyeOff,
  HeartPulse,
  KeyRound,
  ListChecks,
  Lock,
  Monitor,
  PenTool,
  Plane,
  Radar,
  Rocket,
  Scale,
  ShieldCheck,
  Smartphone,
  Watch,
  type LucideIcon,
} from "lucide-react";

import { PRICE_BOOK, formatMoney, perMonth, unitPrices } from "@/components/v2/billing/pricing";

/** Copy and data for the V2 marketing site. Kept in one place so it's easy to edit and translate later. */

export type Buddy = { name: string; icon: LucideIcon; gradient: string; role: string; ask: string; answer: string };

export const BUDDIES: Buddy[] = [
  {
    name: "Travel",
    icon: Plane,
    gradient: "linear-gradient(135deg,#6C63FF,#3B82F6)",
    role: "Flights, trips, visas",
    ask: "Book me to Dubai for the partner meeting, under the travel policy.",
    answer: "Two options under policy. Emirates EK202 is $612 cheaper than yesterday and lands before your 10:00. Want me to hold seat 7A? I'll ask before paying.",
  },
  {
    name: "Finance",
    icon: Coins,
    gradient: "linear-gradient(135deg,#14B8A6,#0EA5E9)",
    role: "Budgets, invoices, expenses",
    ask: "How much of the Q4 design budget is left?",
    answer: "38% is left, about $14,200. Contractor invoices are the biggest line this month. I can't move money, but I can draft the request for Mona.",
  },
  {
    name: "Health",
    icon: HeartPulse,
    gradient: "linear-gradient(135deg,#FF4D6D,#F472B6)",
    role: "Wellness, habits, breaks",
    ask: "I've been in meetings all day.",
    answer: "You've had 5 hours of calls and no break since 11:00. Your next slot is free at 15:30. Want me to hold it for a walk and mute rooms until then?",
  },
  {
    name: "Legal",
    icon: Scale,
    gradient: "linear-gradient(135deg,#F59E0B,#FB923C)",
    role: "Contracts, NDAs, redlines",
    ask: "Is the new NDA safe to sign?",
    answer: "Two clauses need a look: a 5-year term and a non-solicit that covers contractors. I posted a redline to Legal room. Nothing goes to the partner until a person approves.",
  },
  {
    name: "Data",
    icon: Database,
    gradient: "linear-gradient(135deg,#22C55E,#10B981)",
    role: "Dashboards, reports, SQL",
    ask: "What changed in sign-ups this week?",
    answer: "Sign-ups are up 18%, almost all from the Arabic store listing. Here's the chart and the query behind it, so you can check my numbers.",
  },
  {
    name: "Space",
    icon: Rocket,
    gradient: "linear-gradient(135deg,#A855F7,#CC34FF)",
    role: "Projects, launches, roadmaps",
    ask: "What's still blocking the launch?",
    answer: "One blocker: the Android login timeout, fix expected Thursday. Nobody owns the test device yet. Should I create that task for Omar?",
  },
  {
    name: "Design",
    icon: PenTool,
    gradient: "linear-gradient(135deg,#EC4899,#8B5CF6)",
    role: "UI, Figma, design systems",
    ask: "Review the pricing page against our system.",
    answer: "Plan cards use 16px radius, the system says 14. Amber should only mean approval. Body copy is 15px, keep long text at 16.",
  },
  {
    name: "Research",
    icon: BookOpen,
    gradient: "linear-gradient(135deg,#00D4FF,#6366F1)",
    role: "Sources, briefs, summaries",
    ask: "Brief me on vector databases before tomorrow.",
    answer: "Here's a one-page brief with six sources. The short version: start with what you have in Postgres, move only when search latency hurts.",
  },
];

export const STEPS = [
  { title: "Record", text: "Meet in the room, or invite the FloBrain bot to your call." },
  { title: "Transcribe", text: "Speech becomes text on your own server, by speaker, in Arabic and English." },
  { title: "Summarize", text: "A buddy writes the summary and the decisions, with the minute they happened." },
  { title: "Assign", text: "Action items become tasks with an owner and a date, after one click." },
];

export const POLICY = [
  { action: "Search and summarize", rule: "ALLOWED", tone: "ok" },
  { action: "Create tasks", rule: "ASK", tone: "ask" },
  { action: "Send email", rule: "ASK", tone: "ask" },
  { action: "Move money", rule: "NEVER", tone: "no" },
] as const;

export const AUDIT = [
  { at: "10:42", text: "Omar approved the NDA email" },
  { at: "10:42", text: "Legal buddy sent it to counsel" },
  { at: "10:41", text: "Space buddy created a task for Sara" },
  { at: "10:39", text: "External agent output marked untrusted" },
];

export const DEVICES: { name: string; icon: LucideIcon; x: number; y: number }[] = [
  { name: "Wearables", icon: Watch, x: 50, y: 4 },
  { name: "Mobile", icon: Smartphone, x: 93, y: 32 },
  { name: "Web", icon: Monitor, x: 88, y: 76 },
  { name: "Robotics", icon: Bot, x: 50, y: 97 },
  { name: "IoT", icon: Radar, x: 10, y: 76 },
  { name: "Enterprise", icon: Building2, x: 7, y: 32 },
];

export const SECURITY: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: KeyRound, title: "Single sign-on", text: "SAML with your identity provider, and SCIM so people join and leave automatically." },
  { icon: Cloud, title: "Your own cloud", text: "Deploy FloBrain into your AWS account. Your data stays where your company already keeps it." },
  { icon: Lock, title: "Zero data storage", text: "Buddies work on your data in place. Nothing is copied into a vendor's store." },
  { icon: EyeOff, title: "No telemetry", text: "No analytics, no tracking pixels, no usage logs leaving your servers." },
  { icon: ShieldCheck, title: "Scoped AI", text: "Each buddy sees only its room's sources, and only what the person asking can open." },
  { icon: ListChecks, title: "Audit log", text: "Every sign-in, change and approval is recorded and exportable." },
];

export const FAQS = [
  {
    q: "Is FloBrain a chat app, a meeting tool or an AI assistant?",
    a: "All three, in one cockpit. Rooms replace your team chat, meetings run inside the room, and buddies work across both. That's why answers can cite a message, a meeting minute and a task together.",
  },
  {
    q: "What does 'asks before it acts' mean?",
    a: "Buddies can read and suggest freely. Anything that changes data or reaches outside the team, like creating a task, sending an email or booking travel, waits for a person to approve. Admins decide which actions need approval in each room.",
  },
  { q: "Where is our data stored?", a: "In your own AWS account. Meetings are transcribed on your servers, and buddies work on data in place instead of copying it to a vendor." },
  { q: "Which AI models does it use?", a: "Admins choose the models per workspace. You can route fast tasks to a smaller model and keep sensitive rooms on a model you host." },
  { q: "Does it work in Arabic?", a: "Yes. The whole interface works right to left, messages translate between Arabic and English, and search and buddies understand both." },
  { q: "Can we try it before we talk to sales?", a: "Yes. The live demo opens a full workspace with sample rooms, meetings and buddies. No sign-up." },
];

export type Plan = {
  name: string;
  blurb: string;
  monthly: string;
  yearly: string;
  unit: string;
  features: string[];
  cta: string;
  href: string;
  featured?: boolean;
  /** Code in the price book (src/components/v2/billing/pricing.ts), when the plan has a list price. */
  code?: string;
};

export type PriceView = "per_seat" | "per_workspace";

const usd = (cents: number) => formatMoney(cents, "en-US");
const fleet = unitPrices(PRICE_BOOK.fleet);
const studio = unitPrices(PRICE_BOOK.studio);

const CREW: Plan = {
  code: "crew",
  name: "Crew",
  blurb: "For small teams getting started.",
  monthly: usd(PRICE_BOOK.crew.monthCents ?? 0),
  yearly: usd(PRICE_BOOK.crew.monthCents ?? 0),
  unit: `free forever, up to ${PRICE_BOOK.crew.seatCap} people`,
  features: ["Rooms, DMs and threads", "Meetings up to 40 minutes", "3 buddies", "Tasks and time tracking", "7 days of history"],
  cta: "Start free",
  href: "/w/signin",
};

const MISSION: Plan = {
  name: "Mission",
  blurb: "For companies with their own cloud and rules.",
  monthly: "Custom",
  yearly: "Custom",
  unit: "yearly agreement",
  features: ["Everything in Fleet", "Deploy in your AWS account", "SSO, SCIM and audit log", "Bring your own models", "Data residency and DPA", "Dedicated support"],
  cta: "Talk to us",
  href: "/contact",
};

/**
 * Sample prices for the design. Final pricing is still to be confirmed (docs/v2/DECISIONS_NEEDED.md).
 * Numbers come from the price book (src/components/v2/billing/pricing.ts), never written here.
 */
export const PLANS: Plan[] = [
  CREW,
  {
    code: "fleet",
    name: "Fleet",
    blurb: "For teams that run on FloBrain every day.",
    monthly: usd(fleet.month ?? 0),
    yearly: usd(perMonth(fleet.year ?? 0)),
    unit: "per person, per month",
    features: ["Everything in Crew", "Unlimited meetings with transcripts", "Unlimited buddies and Buddy studio", "Approvals and room policies", "Reports and impact score", "Unlimited history"],
    cta: "Start a 14 day trial",
    href: "/w/signin",
    featured: true,
  },
  MISSION,
];

/** The same plans with one flat price for the whole workspace (Studio instead of Fleet). */
export const WORKSPACE_PLANS: Plan[] = [
  CREW,
  {
    code: "studio",
    name: "Studio",
    blurb: `Everything in Fleet for one price, up to ${PRICE_BOOK.studio.seatCap} people.`,
    monthly: usd(studio.month ?? 0),
    yearly: usd(perMonth(studio.year ?? 0)),
    unit: `per workspace, per month, up to ${PRICE_BOOK.studio.seatCap} people`,
    features: [
      "Everything in Fleet",
      `Up to ${PRICE_BOOK.studio.seatCap} people, one price`,
      `${(PRICE_BOOK.studio.aiPerWorkspace ?? 0).toLocaleString("en-US")} buddy answers a month, shared`,
      "No surprise charges: invites stop at the cap",
      "Switch to per person any time",
    ],
    cta: "Start a 14 day trial",
    href: "/w/signin",
    featured: true,
  },
  MISSION,
];

export const PLAN_VIEWS: Record<PriceView, Plan[]> = { per_seat: PLANS, per_workspace: WORKSPACE_PLANS };

const ai = (n: number | null) => (n ?? 0).toLocaleString("en-US");

/** Columns: Crew, Fleet (per person), Studio (per workspace), Mission. */
export const COMPARE_PLANS = ["Crew", "Fleet", "Studio", "Mission"] as const;

export const COMPARE: [string, string, string, string, string][] = [
  ["How you pay", "Free", "Per person", "Per workspace", "Yearly agreement"],
  ["People", `Up to ${PRICE_BOOK.crew.seatCap}`, "Any number", `Up to ${PRICE_BOOK.studio.seatCap}`, "Any number"],
  ["AI answers included each month", `${ai(PRICE_BOOK.crew.aiPerSeat)} per person`, `${ai(PRICE_BOOK.fleet.aiPerSeat)} per person`, `${ai(PRICE_BOOK.studio.aiPerWorkspace)} per workspace`, "Custom"],
  ["Rooms and DMs", "yes", "yes", "yes", "yes"],
  ["Meeting length", "40 min", "Unlimited", "Unlimited", "Unlimited"],
  ["Transcripts and summaries", "", "yes", "yes", "yes"],
  ["Buddies", "3", "Unlimited", "Unlimited", "Unlimited"],
  ["Buddy studio", "", "yes", "yes", "yes"],
  ["Approvals and policies", "", "yes", "yes", "yes"],
  ["Reports and impact", "Personal", "Team", "Team", "Team + export"],
  ["SSO and SCIM", "", "", "", "yes"],
  ["Deploy in your cloud", "", "", "", "yes"],
  ["Bring your own models", "", "", "", "yes"],
  ["Support", "Community", "Email", "Email", "Dedicated"],
];
