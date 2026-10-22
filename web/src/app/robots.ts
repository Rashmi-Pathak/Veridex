import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

// Crawlable by all user agents, with a pointer to the sitemap.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
