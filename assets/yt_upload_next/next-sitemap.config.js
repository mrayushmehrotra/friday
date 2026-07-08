/** @type {import('next-sitemap').IConfig} */
module.exports = {
  siteUrl: process.env.SITE_URL || "https://vercel.invid.ai",
  generateRobotsTxt: true,
  sitemapSize: 7000,
  changefreq: "daily",
  priority: 0.7,
  exclude: ["/dashboard/*", "/sign-in", "/sign-up"],
  additionalPaths: async (config) => [
    await config.transform(config, "/"),
    await config.transform(config, "/dashboard"),
    await config.transform(config, "/dashboard/"),
  ],
  robotsTxtOptions: {
    policies: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/dashboard/", "/api/", "/sign-in", "/sign-up"],
      },
    ],
  },
};
