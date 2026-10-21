"use client";

import { useParams } from "next/navigation";

import { WebsiteChat } from "@/components/v2/channels/WebsiteChat";
import "@/styles/v2-tokens.css";

/** The website chat customers see, inside the widget's iframe or on its own. Signed out, no cookies. */
export default function WebsiteChatPage() {
  const { siteKey } = useParams<{ siteKey: string }>();
  return <WebsiteChat siteKey={siteKey} />;
}
