import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

// The homepage. Receipt permalinks (/r/<manifestId>) are per-instance and not enumerated here.
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1,
    },
  ];
}
