import { google } from "googleapis";
import { type NextRequest, NextResponse } from "next/server";
import { Readable } from "stream";
import {
  User,
  getSessionExpiryDate,
  checkSession,
} from "@/lib/models";

// CORS headers for cross-origin requests (mobile app on different port)
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

/**
 * Handle CORS preflight requests
 */
export async function OPTIONS() {
  return NextResponse.json({}, { headers: corsHeaders });
}

/**
 * Sanitize tags for YouTube API requirements
 */
function sanitizeTags(tags: string[]): string[] {
  if (!tags || !Array.isArray(tags)) return [];

  const sanitized: string[] = [];
  let totalLength = 0;
  const maxTotalLength = 500;

  for (const tag of tags) {
    let cleanTag = tag
      .replace(/#/g, "")
      .replace(/[<>]/g, "")
      .replace(/\s+/g, " ")
      .trim();

    if (!cleanTag) continue;
    if (cleanTag.length > 30) {
      cleanTag = cleanTag.substring(0, 30).trim();
    }

    const tagLength = cleanTag.length + (sanitized.length > 0 ? 1 : 0);
    if (totalLength + tagLength > maxTotalLength) break;

    sanitized.push(cleanTag);
    totalLength += tagLength;
  }

  return sanitized;
}

const oauth2Client = new google.auth.OAuth2(
  process.env.GOOGLE_CLIENT_ID,
  process.env.GOOGLE_CLIENT_SECRET,
  process.env.GOOGLE_REDIRECT_URI,
);

async function createYouTubeClient(accessToken: string, userId?: string) {
  const client = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    process.env.GOOGLE_REDIRECT_URI,
  );

  let refreshToken: string | undefined;
  if (userId) {
    const user = await User.findById(userId);
    if (user) {
      refreshToken = user.youtubeRefreshToken;
    }
  }

  client.setCredentials({
    access_token: accessToken,
    refresh_token: refreshToken,
  });

  if (userId && refreshToken) {
    client.on("tokens", async (tokens) => {
      if (tokens.access_token) {
        await User.findByIdAndUpdate(userId, {
          $set: { youtubeAccessToken: tokens.access_token },
        });
      }
    });
  }

  return {
    youtube: google.youtube({ version: "v3", auth: client }),
    youtubeAnalytics: google.youtubeAnalytics({ version: "v2", auth: client }),
  };
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get("action");
  const code = searchParams.get("code");

  if (action === "auth") {
    console.log("🔍 YouTube Auth: Generating auth URL");
    const authUrl = oauth2Client.generateAuthUrl({
      access_type: "offline",
      prompt: "consent", // Force to get refresh token
      scope: [
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
      ],
    });
    console.log("✅ YouTube Auth: Auth URL generated successfully");
    return NextResponse.json({ authUrl }, { headers: corsHeaders });
  }

  if (action === "callback" && code) {
    try {
      console.log("🔍 YouTube Callback: Received code, exchanging for tokens");
      const { tokens } = await oauth2Client.getToken(code);
      oauth2Client.setCredentials(tokens);
      console.log("✅ YouTube Callback: Tokens exchanged successfully");

      const html = `
        <html>
          <body>
            <script>
              // Use '*' to allow cross-origin (mobile app may be on different port)
              // In production, you'd use a specific origin
              window.opener.postMessage({ type: 'GOOGLE_AUTH_SUCCESS', tokens: ${JSON.stringify(tokens)} }, '*');
              window.close();
            </script>
          </body>
        </html>
      `;

      return new NextResponse(html, {
        headers: { "Content-Type": "text/html", ...corsHeaders },
      });
    } catch (_error) {
      return NextResponse.json(
        { error: "Authentication failed" },
        { status: 400, headers: corsHeaders },
      );
    }
  }

  return NextResponse.json(
    { error: "Invalid request" },
    { status: 400, headers: corsHeaders },
  );
}

export async function POST(request: NextRequest) {
  try {
    const contentType = request.headers.get("content-type") || "";

    let action, accessToken, data, userId;

    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      action = formData.get("action") as string;
      accessToken = formData.get("accessToken") as string;
      userId = formData.get("userId") as string;
      data = {
        title: formData.get("title") as string,
        description: formData.get("description") as string,
        tags:
          (formData.get("tags") as string)?.split(",").map((t) => t.trim()) ||
          [],
        privacy: formData.get("privacy") as string,
        videoFile: formData.get("videoFile") as File,
      };
    } else {
      const jsonBody = await request.json();
      action = jsonBody.action;
      accessToken = jsonBody.accessToken;
      userId = jsonBody.userId;
      const { action: _a, accessToken: _at, userId: _uid, ...rest } = jsonBody;
      data = rest;
    }

    // =====================================================
    // ACTION: Exchange Code & Save User to Database
    // =====================================================
    if (action === "exchangeCode") {
      console.log("🔍 YouTube Exchange: Starting code exchange");
      console.log("📝 Code received:", data.code?.substring(0, 20) + "...");

      let tokens;
      try {
        tokens = await oauth2Client.getToken(data.code);
        oauth2Client.setCredentials(tokens.tokens);
        console.log("✅ YouTube Exchange: Code exchanged successfully");
        console.log("🎫 Tokens received:", Object.keys(tokens.tokens));
      } catch (error: any) {
        console.error(
          "❌ YouTube Exchange: Token exchange failed:",
          error.message,
        );
        console.error("🔍 Error details:", error.code, error.status);

        if (error.code === 400 && error.message?.includes("invalid_grant")) {
          console.error("💡 This usually means:");
          console.error("   - Code expired (codes last ~10 minutes)");
          console.error("   - Code already used");
          console.error("   - Redirect URI mismatch");
        }

        return NextResponse.json(
          {
            error: "Failed to exchange authorization code. Please try again.",
            details: error.message,
          },
          { status: 400, headers: corsHeaders },
        );
      }

      // Get user info from Google
      const oauth2 = google.oauth2({ version: "v2", auth: oauth2Client });
      const userInfoResponse = await oauth2.userinfo.get();
      const userInfo = userInfoResponse.data;
      console.log("👤 User info retrieved:", userInfo.email);

      // Get YouTube channel info
      const youtube = google.youtube({ version: "v3", auth: oauth2Client });
      const channelResponse = await youtube.channels.list({
        part: ["snippet", "statistics"],
        mine: true,
      });
      const channel = channelResponse.data.items?.[0];

      // Session expires in 24 hours
      const sessionExpiresAt = getSessionExpiryDate();

      console.log(userInfo, "this is the user info");
      const existingUser = await User.findOne({ email: userInfo.email });

      let user;
      console.log(existingUser, "is there?");
      if (existingUser) {
        console.log("im inside exisitng user");

        // Update existing user with new YouTube tokens
        user = await User.findByIdAndUpdate(
          existingUser._id,
          {
            $set: {
              name: userInfo.name,
              image: userInfo.picture,
              youtubeChannelId: channel?.id,
              youtubeChannelName: channel?.snippet?.title,
              youtubeChannelImage: channel?.snippet?.thumbnails?.default?.url,
              youtubeAccessToken: tokens.access_token,
              youtubeRefreshToken:
                tokens.refresh_token || existingUser.youtubeRefreshToken,
              youtubeConnectedAt: new Date(),
              sessionExpiresAt: sessionExpiresAt,
            },
          },
          { new: true },
        );
      } else {
        // Create new user
        user = await User.create({
          _id: crypto.randomUUID(),
          email: userInfo.email!,
          name: userInfo.name,
          image: userInfo.picture,
          youtubeChannelId: channel?.id,
          youtubeChannelName: channel?.snippet?.title,
          youtubeChannelImage: channel?.snippet?.thumbnails?.default?.url,
          youtubeAccessToken: tokens.access_token,
          youtubeRefreshToken: tokens.refresh_token,
          youtubeConnectedAt: new Date(),
          sessionExpiresAt: sessionExpiresAt,
          plan: "free",
        });
      }

      const response = NextResponse.json({
        success: true,
        tokens: tokens.tokens,
        user: {
          id: user._id,
          email: user.email,
          name: user.name,
          image: user.image,
          plan: user.plan,
          youtubeChannelId: user.youtubeChannelId,
          youtubeChannelName: user.youtubeChannelName,
          youtubeChannelImage: user.youtubeChannelImage,
          sessionExpiresAt: user.sessionExpiresAt,
        },
      });

      if (tokens.tokens.access_token) {
        // Set cookies to expire with session (24 hours)
        response.cookies.set(
          "youtube_access_token",
          tokens.tokens.access_token,
          {
            httpOnly: false,
            secure: process.env.NODE_ENV === "production",
            sameSite: "lax",
            path: "/",
            maxAge: 60 * 60 * 24, // 24 hours
          },
        );
        response.cookies.set("user_id", user._id, {
          httpOnly: false,
          secure: process.env.NODE_ENV === "production",
          sameSite: "lax",
          path: "/",
          maxAge: 60 * 60 * 24, // 24 hours
        });
      }

      return response;
    }

    // =====================================================
    // ACTION: Check Session (is user still logged in?)
    // =====================================================
    if (action === "checkSession") {
      if (!userId) {
        return NextResponse.json(
          { valid: false, error: "User ID required" },
          { status: 400 },
        );
      }

      const session = await checkSession(userId);

      if (!session.valid) {
        return NextResponse.json({
          valid: false,
          error: "Session expired. Please reconnect your YouTube account.",
          expired: true,
        });
      }

      return NextResponse.json({
        success: true,
        valid: true,
        user: session.user
          ? {
              id: session.user._id,
              email: session.user.email,
              name: session.user.name,
              image: session.user.image,
              plan: session.user.plan,
              youtubeChannelId: session.user.youtubeChannelId,
              youtubeChannelName: session.user.youtubeChannelName,
            }
          : null,
        expiresAt: session.expiresAt,
        remainingHours: session.remainingHours,
      });
    }

    if (!accessToken) {
      return NextResponse.json(
        { error: "Missing access token" },
        { status: 401 },
      );
    }

    const { youtube, youtubeAnalytics } = await createYouTubeClient(
      accessToken,
      userId,
    );

    // =====================================================
    // ACTION: Update Video
    // =====================================================
    if (action === "updateVideo") {
      try {
        if (!data.videoId) {
          return NextResponse.json(
            { success: false, error: "Video ID is required" },
            { status: 400 },
          );
        }

        if (!data.title || data.title.trim().length === 0) {
          return NextResponse.json(
            { success: false, error: "Title is required" },
            { status: 400 },
          );
        }

        const currentVideo = await youtube.videos.list({
          part: ["snippet"],
          id: [data.videoId],
        });

        const currentSnippet = currentVideo.data.items?.[0]?.snippet;
        if (!currentSnippet) {
          return NextResponse.json(
            { success: false, error: "Video not found" },
            { status: 404 },
          );
        }

        const response = await youtube.videos.update({
          part: ["snippet"],
          requestBody: {
            id: data.videoId,
            snippet: {
              ...currentSnippet,
              title: data.title,
              description: data.description || "",
              tags: sanitizeTags(data.tags || []),
              categoryId: currentSnippet.categoryId,
            },
          },
        });

        return NextResponse.json({ success: true, data: response.data });
      } catch (error: any) {
        console.error("Update Video Error:", error);
        const errorMessage =
          error.response?.data?.error?.message ||
          error.message ||
          "Failed to update video";
        return NextResponse.json(
          { success: false, error: errorMessage },
          { status: error.response?.status || 500 },
        );
      }
    }

    // =====================================================
    // ACTION: Upload Video
    // =====================================================
    if (action === "uploadVideo") {
      try {
        if (!data.videoFile) {
          return NextResponse.json(
            { error: "No video file provided" },
            { status: 400 },
          );
        }

        const buffer = Buffer.from(await data.videoFile.arrayBuffer());
        const stream = Readable.from(buffer);

        const response = await youtube.videos.insert({
          part: ["snippet", "status"],
          requestBody: {
            snippet: {
              title: data.title,
              description: data.description,
              tags: sanitizeTags(data.tags || []),
            },
            status: {
              privacyStatus: data.privacy || "private",
            },
          },
          media: {
            body: stream,
          },
        });

        return NextResponse.json({ success: true, videoId: response.data.id });
      } catch (error: any) {
        console.error("Upload Video Error:", error);
        const errMsg =
          error.response?.data?.error?.message ||
          error.message ||
          "Failed to upload video";
        return NextResponse.json(
          { success: false, error: errMsg },
          { status: error.response?.status || 500 },
        );
      }
    }

    // =====================================================
    // ACTION: Get Channel Data
    // =====================================================
    if (action === "getChannelData") {
      try {
        const channelResponse = await youtube.channels.list({
          part: ["snippet", "statistics", "brandingSettings", "contentDetails"],
          mine: true,
        });

        const channel = channelResponse.data.items?.[0];
        const uploadsPlaylistId =
          channel?.contentDetails?.relatedPlaylists?.uploads;

        let recentVideos: any[] = [];
        if (uploadsPlaylistId) {
          const videosResponse = await youtube.playlistItems.list({
            part: ["snippet", "status"],
            playlistId: uploadsPlaylistId,
            maxResults: 50,
          });

          const playlistItems = videosResponse.data.items || [];

          const videoIds = playlistItems
            .map((item: any) => item.snippet?.resourceId?.videoId)
            .filter(Boolean);

          if (videoIds.length > 0) {
            const statsResponse = await youtube.videos.list({
              part: ["statistics", "contentDetails"],
              id: videoIds,
            });

            const videoStats = statsResponse.data.items || [];
            const statsMap = new Map(
              videoStats.map((video: any) => [video.id, video]),
            );

            recentVideos = playlistItems.map((item: any) => {
              const videoId = item.snippet?.resourceId?.videoId;
              const stats = statsMap.get(videoId);
              return {
                ...item,
                statistics: stats?.statistics,
                contentDetails: stats?.contentDetails,
              };
            });
          } else {
            recentVideos = playlistItems;
          }
        }

        return NextResponse.json({
          success: true,
          statistics: channel?.statistics || {},
          videos: recentVideos,
        });
      } catch (error: any) {
        console.error("Get Channel Data Error:", error);
        const errMsg =
          error.response?.data?.error?.message ||
          error.message ||
          "Failed to fetch channel data";
        return NextResponse.json(
          { success: false, error: errMsg },
          { status: error.response?.status || 500 },
        );
      }
    }

    // =====================================================
    // ACTION: Get Analytics
    // =====================================================
    if (action === "getAnalytics") {
      try {
        const endDate = new Date().toISOString().split("T")[0];
        const startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)
          .toISOString()
          .split("T")[0];

        const channelResponse = await youtube.channels.list({
          part: ["id"],
          mine: true,
        });

        const channelId = channelResponse.data.items?.[0]?.id;

        if (!channelId) {
          return NextResponse.json(
            { error: "Channel not found" },
            { status: 404 },
          );
        }

        const analyticsResponse = await youtubeAnalytics.reports.query({
          ids: `channel==${channelId}`,
          startDate,
          endDate,
          metrics:
            "views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
          dimensions: "day",
        });

        const overviewResponse = await youtubeAnalytics.reports.query({
          ids: `channel==${channelId}`,
          startDate,
          endDate,
          metrics:
            "views,estimatedMinutesWatched,likes,comments,shares,subscribersGained",
        });

        const overviewColumns =
          overviewResponse.data.columnHeaders?.map((h: any) => h.name) || [];
        const overviewRow = overviewResponse.data.rows?.[0] || [];
        const rawAnalytics: Record<string, number> = {};
        overviewColumns.forEach((name: string, i: number) => {
          rawAnalytics[name] = Number(overviewRow[i]) || 0;
        });

        return NextResponse.json({
          success: true,
          analytics: {
            views: rawAnalytics.views || 0,
            watchTime: rawAnalytics.estimatedMinutesWatched || 0,
            likes: rawAnalytics.likes || 0,
            subscribersGained: rawAnalytics.subscribersGained || 0,
          },
        });
      } catch (error: any) {
        console.error("Get Analytics Error:", error);
        const errMsg =
          error.response?.data?.error?.message ||
          error.message ||
          "Failed to fetch analytics";
        return NextResponse.json(
          { success: false, error: errMsg },
          { status: error.response?.status || 500 },
        );
      }
    }

    // =====================================================
    // ACTION: Get Video Analytics
    // =====================================================
    if (action === "getVideoAnalytics") {
      try {
        const endDate = new Date().toISOString().split("T")[0];
        const startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)
          .toISOString()
          .split("T")[0];

        const response = await youtubeAnalytics.reports.query({
          ids: `video==${data.videoId}`,
          startDate,
          endDate,
          metrics:
            "views,likes,dislikes,comments,shares,estimatedMinutesWatched,averageViewDuration",
        });

        return NextResponse.json({ success: true, data: response.data });
      } catch (error: any) {
        console.error("Get Video Analytics Error:", error);
        const errMsg =
          error.response?.data?.error?.message ||
          error.message ||
          "Failed to fetch video analytics";
        return NextResponse.json(
          { success: false, error: errMsg },
          { status: error.response?.status || 500 },
        );
      }
    }

    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  } catch (error) {
    console.error("API Error:", error);
    return NextResponse.json({ error: "session expired" }, { status: 500 });
  }
}
